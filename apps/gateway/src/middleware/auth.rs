use axum::http::HeaderMap;
use jsonwebtoken::{decode, DecodingKey, Validation};
use serde::{Deserialize, Serialize};

use crate::error::AppError;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Claims {
    pub sub: String,
    pub exp: usize,
}

fn decode_bearer(token: &str, jwt_secret: &str) -> Option<Claims> {
    decode::<Claims>(
        token,
        &DecodingKey::from_secret(jwt_secret.as_bytes()),
        &Validation::default(),
    )
    .ok()
    .map(|data| data.claims)
}

/// Best-effort JWT extraction. Returns `Some(user_id)` for a valid bearer
/// token, `None` otherwise (falls back to per-IP rate limiting upstream).
pub fn extract_user_id(headers: &HeaderMap, jwt_secret: &str) -> Option<String> {
    let auth = headers.get(axum::http::header::AUTHORIZATION)?.to_str().ok()?;
    let token = auth.strip_prefix("Bearer ")?;
    decode_bearer(token, jwt_secret).map(|c| c.sub)
}

/// Hard-required JWT extraction for routes with no anonymous path --
/// alert subscriptions are inherently per-user, unlike search/geocode/
/// research which accept anonymous requests (see `extract_user_id`).
/// Returns `AppError::Unauthorized` (401) rather than falling back to
/// anything.
pub fn require_user_id(headers: &HeaderMap, jwt_secret: &str) -> Result<String, AppError> {
    extract_user_id(headers, jwt_secret).ok_or(AppError::Unauthorized)
}

/// Same as `require_user_id` but reads the token from a query parameter
/// instead of the Authorization header -- browsers' native WebSocket API
/// can't set custom headers during the handshake, so `?token=...` is the
/// common pattern for authenticating a WS upgrade. Known tradeoff: query
/// strings can end up in server access logs and browser history. Mitigate
/// by using short-lived tokens; a cookie- or subprotocol-based handshake
/// is the fuller fix and is future work, not attempted here.
pub fn require_user_id_from_query(token: Option<&str>, jwt_secret: &str) -> Result<String, AppError> {
    let token = token.ok_or(AppError::Unauthorized)?;
    decode_bearer(token, jwt_secret)
        .map(|c| c.sub)
        .ok_or(AppError::Unauthorized)
}
