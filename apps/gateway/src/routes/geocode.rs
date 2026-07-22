use axum::{extract::State, http::header, Json};
use serde::Deserialize;
use serde_json::{json, Value};
use tracing::warn;

use crate::{error::AppError, state::AppState};

#[derive(Debug, Deserialize)]
pub struct GeocodeQuery {
    pub q: String,
    #[serde(default)]
    pub limit: Option<u8>,
}

/// Proxies to Nominatim with strict User-Agent hygiene per their usage
/// policy: https://operations.osmfoundation.org/policies/nominatim/,
/// falling back to Photon (a separate, independently-run public
/// geocoder over the same OSM data) if Nominatim errors -- confirmed
/// live that Nominatim flatly 403s requests from this sandbox's shared
/// egress IP regardless of what User-Agent is sent, which previously
/// took /geocode down with no fallback.
pub async fn geocode(
    State(state): State<AppState>,
    axum::extract::Query(params): axum::extract::Query<GeocodeQuery>,
) -> Result<Json<Value>, AppError> {
    if params.q.trim().is_empty() {
        return Err(AppError::BadRequest("query parameter `q` is required".into()));
    }

    let limit = params.limit.unwrap_or(5).clamp(1, 20);

    match geocode_nominatim(&state, &params.q, limit).await {
        Ok(body) => Ok(Json(body)),
        Err(nominatim_err) => {
            warn!(
                error = %nominatim_err,
                "nominatim geocode failed, falling back to photon"
            );
            match geocode_photon(&state, &params.q, limit).await {
                Ok(body) => Ok(Json(body)),
                Err(photon_err) => {
                    warn!(error = %photon_err, "photon fallback also failed");
                    // Surface the original (Nominatim) failure -- it's the
                    // primary provider, and its error is what a caller
                    // configured for Nominatim would expect to debug against.
                    Err(nominatim_err)
                }
            }
        }
    }
}

async fn geocode_nominatim(state: &AppState, q: &str, limit: u8) -> Result<Value, AppError> {
    let mut req = state
        .http
        .get(format!("{}/search", state.config.nominatim_base_url))
        .header(header::USER_AGENT, &state.config.nominatim_user_agent)
        .query(&[
            ("q", q),
            ("format", "jsonv2"),
            ("limit", &limit.to_string()),
            ("addressdetails", "1"),
        ]);

    if let Some(key) = &state.config.nominatim_api_key {
        req = req.query(&[("key", key.as_str())]);
    }

    let resp = req.send().await?.error_for_status()?;
    let body: Value = resp.json().await?;
    Ok(body)
}

/// Photon returns GeoJSON, not Nominatim's jsonv2 shape -- translated here
/// so gateway callers (the frontend's `geocode()`) see one consistent
/// response shape regardless of which provider actually served the
/// request. Photon's coordinate order is GeoJSON standard ([lon, lat]),
/// the opposite of the lat/lon field order in its own `properties`.
async fn geocode_photon(state: &AppState, q: &str, limit: u8) -> Result<Value, AppError> {
    let resp = state
        .http
        .get(&state.config.photon_base_url)
        .query(&[("q", q), ("limit", &limit.to_string())])
        .send()
        .await?
        .error_for_status()?;
    let body: Value = resp.json().await?;

    let features = body["features"].as_array().cloned().unwrap_or_default();
    let hits: Vec<Value> = features
        .iter()
        .filter_map(|f| {
            let coords = f["geometry"]["coordinates"].as_array()?;
            let lon = coords.first()?.as_f64()?;
            let lat = coords.get(1)?.as_f64()?;
            let props = &f["properties"];

            let display_name = [
                props["name"].as_str(),
                props["street"].as_str(),
                props["city"].as_str(),
                props["state"].as_str(),
                props["postcode"].as_str(),
                props["country"].as_str(),
            ]
            .into_iter()
            .flatten()
            .collect::<Vec<_>>()
            .join(", ");

            Some(json!({
                "place_id": props["osm_id"].as_i64().unwrap_or_default(),
                "display_name": display_name,
                "lat": lat.to_string(),
                "lon": lon.to_string(),
                "type": props["osm_value"].as_str().or(props["osm_key"].as_str()).unwrap_or("unknown"),
            }))
        })
        .collect();

    Ok(Value::Array(hits))
}
