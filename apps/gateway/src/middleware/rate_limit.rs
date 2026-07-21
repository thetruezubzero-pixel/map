use axum::{
    body::Body,
    extract::{ConnectInfo, State},
    http::Request,
    middleware::Next,
    response::Response,
};
use std::net::SocketAddr;

use crate::{error::AppError, middleware::auth::extract_user_id, state::AppState};

/// Applies per-user rate limiting when a valid JWT is present, otherwise
/// falls back to per-IP rate limiting. Per-user limits are more generous
/// (see `Config::authed_rate_limit_per_sec`).
pub async fn rate_limit(
    State(state): State<AppState>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    request: Request<Body>,
    next: Next,
) -> Result<Response, AppError> {
    let user_id = extract_user_id(request.headers(), &state.config.jwt_secret);

    let allowed = match &user_id {
        Some(uid) => state.user_limiter.check_key(uid).is_ok(),
        None => state.ip_limiter.check_key(&addr.ip().to_string()).is_ok(),
    };

    if !allowed {
        return Err(AppError::RateLimited);
    }

    Ok(next.run(request).await)
}
