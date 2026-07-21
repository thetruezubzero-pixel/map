use std::env;

use axum::extract::Request;
use axum::http::StatusCode;
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};

/// Basic request-frequency-adjacent hygiene check: rejects requests with a
/// missing/blank User-Agent, and requests whose User-Agent matches an
/// operator-configured blocklist (BOT_BLOCKLIST, comma-separated substrings,
/// case-insensitive). This is anomaly logging + a hygiene gate for this
/// service's own endpoints, not client fingerprinting or third-party
/// evasion tooling.
pub async fn reject_suspicious_requests(request: Request, next: Next) -> Response {
    let user_agent = request
        .headers()
        .get(axum::http::header::USER_AGENT)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();

    if user_agent.trim().is_empty() {
        tracing::warn!(path = %request.uri().path(), "rejected request with missing User-Agent");
        return (StatusCode::FORBIDDEN, "User-Agent header is required").into_response();
    }

    let blocklist = env::var("BOT_BLOCKLIST").unwrap_or_default();
    let ua_lower = user_agent.to_lowercase();
    for pattern in blocklist.split(',').map(str::trim).filter(|p| !p.is_empty()) {
        if ua_lower.contains(&pattern.to_lowercase()) {
            tracing::warn!(
                path = %request.uri().path(),
                user_agent = %user_agent,
                "rejected request matching bot blocklist"
            );
            return (StatusCode::FORBIDDEN, "request blocked").into_response();
        }
    }

    next.run(request).await
}
