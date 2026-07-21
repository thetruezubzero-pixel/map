use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::Value;

use crate::AppState;

#[derive(Deserialize)]
pub struct GeocodeQuery {
    q: String,
    #[serde(default = "default_limit")]
    limit: u8,
}

fn default_limit() -> u8 {
    5
}

pub async fn geocode(
    State(state): State<Arc<AppState>>,
    Query(params): Query<GeocodeQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let query = params.q.trim();
    if query.is_empty() {
        return Err((StatusCode::BAD_REQUEST, "query parameter 'q' is required".into()));
    }
    let limit = params.limit.clamp(1, 20);

    let mut request = state
        .http_client
        .get(format!("{}/search", state.nominatim_base_url))
        .query(&[
            ("q", query),
            ("format", "jsonv2"),
            ("limit", &limit.to_string()),
        ]);

    if let Ok(contact) = std::env::var("OPERATOR_CONTACT") {
        if !contact.is_empty() {
            request = request.query(&[("email", contact.as_str())]);
        }
    }

    let response = request.send().await.map_err(|err| {
        tracing::warn!(error = %err, "nominatim request failed");
        (StatusCode::BAD_GATEWAY, "upstream geocoding provider unavailable".into())
    })?;

    if !response.status().is_success() {
        let status = response.status();
        tracing::warn!(%status, "nominatim returned non-success status");
        return Err((StatusCode::BAD_GATEWAY, "upstream geocoding provider error".into()));
    }

    let body: Value = response.json().await.map_err(|err| {
        tracing::warn!(error = %err, "failed to parse nominatim response");
        (StatusCode::BAD_GATEWAY, "invalid response from upstream provider".into())
    })?;

    Ok(Json(body))
}
