use axum::{extract::State, http::HeaderMap, Json};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    error::AppError,
    middleware::auth::extract_user_id,
    state::AppState,
};

#[derive(Debug, Deserialize)]
pub struct ResearchRequest {
    /// Natural-language research query, e.g. "corporate subsidiaries of
    /// Acme Holdings registered in Delaware since 2020". Public business
    /// and property records only -- see ROADMAP.md.
    pub query: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ResearchJobResponse {
    pub job_id: String,
    pub status: String,
}

/// Kicks off an async multi-agent research job by forwarding to the
/// Python orchestration service. Returns immediately with a job ID;
/// jobs queue for human review before finalization (see apps/api/python).
pub async fn create_research_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<ResearchRequest>,
) -> Result<Json<ResearchJobResponse>, AppError> {
    if payload.query.trim().is_empty() {
        return Err(AppError::BadRequest("`query` must not be empty".into()));
    }
    if payload.query.len() > 2000 {
        return Err(AppError::BadRequest("`query` exceeds max length (2000 chars)".into()));
    }

    let user_id = extract_user_id(&headers, &state.config.jwt_secret);

    let resp = state
        .http
        .post(format!("{}/research", state.config.python_api_base_url))
        .json(&serde_json::json!({
            "query": payload.query,
            "requested_by": user_id,
        }))
        .send()
        .await?
        .error_for_status()?;

    let body: Value = resp.json().await?;
    let job_id = body
        .get("job_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| AppError::BadRequest("orchestration service returned no job_id".into()))?
        .to_string();

    Ok(Json(ResearchJobResponse {
        job_id,
        status: "queued".to_string(),
    }))
}
