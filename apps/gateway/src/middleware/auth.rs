use axum::http::HeaderMap;
use jsonwebtoken::{decode, DecodingKey, Validation};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Claims {
    pub sub: String,
    pub exp: usize,
}

/// Best-effort JWT extraction. Returns `Some(user_id)` for a valid bearer
/// token, `None` otherwise (falls back to per-IP rate limiting upstream).
pub fn extract_user_id(headers: &HeaderMap, jwt_secret: &str) -> Option<String> {
    let auth = headers.get(axum::http::header::AUTHORIZATION)?.to_str().ok()?;
    let token = auth.strip_prefix("Bearer ")?;

    let data = decode::<Claims>(
        token,
        &DecodingKey::from_secret(jwt_secret.as_bytes()),
        &Validation::default(),
    )
    .ok()?;

    Some(data.claims.sub)
}
