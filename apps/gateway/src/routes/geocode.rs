use axum::{extract::State, http::header, Json};
use serde::Deserialize;
use serde_json::Value;

use crate::{error::AppError, state::AppState};

#[derive(Debug, Deserialize)]
pub struct GeocodeQuery {
    pub q: String,
    #[serde(default)]
    pub limit: Option<u8>,
}

/// Proxies to Nominatim with strict User-Agent hygiene per their usage
/// policy: https://operations.osmfoundation.org/policies/nominatim/
pub async fn geocode(
    State(state): State<AppState>,
    axum::extract::Query(params): axum::extract::Query<GeocodeQuery>,
) -> Result<Json<Value>, AppError> {
    if params.q.trim().is_empty() {
        return Err(AppError::BadRequest("query parameter `q` is required".into()));
    }

    let limit = params.limit.unwrap_or(5).clamp(1, 20);

    let mut req = state
        .http
        .get(format!("{}/search", state.config.nominatim_base_url))
        .header(header::USER_AGENT, &state.config.nominatim_user_agent)
        .query(&[
            ("q", params.q.as_str()),
            ("format", "jsonv2"),
            ("limit", &limit.to_string()),
            ("addressdetails", "1"),
        ]);

    if let Some(key) = &state.config.nominatim_api_key {
        req = req.query(&[("key", key.as_str())]);
    }

    let resp = req.send().await?.error_for_status()?;
    let body: Value = resp.json().await?;

    Ok(Json(body))
}
