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

#[cfg(test)]
mod tests {
    //! The gateway had no test coverage at all; these lock in the
    //! security-critical properties of the auth boundary so a future
    //! change that weakens them (widening the accepted algorithm set,
    //! dropping exp validation, accepting a token without the Bearer
    //! prefix) fails CI instead of shipping silently.
    use super::*;
    use axum::http::header::AUTHORIZATION;
    use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};

    const SECRET: &str = "test-secret-not-a-real-one";

    fn token_signed_with(alg: Algorithm, sub: &str, exp_offset_secs: i64, secret: &str) -> String {
        let exp = (chrono::Utc::now().timestamp() + exp_offset_secs) as usize;
        let claims = Claims { sub: sub.to_string(), exp };
        encode(&Header::new(alg), &claims, &EncodingKey::from_secret(secret.as_bytes())).unwrap()
    }

    fn make_token(sub: &str, exp_offset_secs: i64) -> String {
        token_signed_with(Algorithm::HS256, sub, exp_offset_secs, SECRET)
    }

    fn bearer(token: &str) -> HeaderMap {
        let mut h = HeaderMap::new();
        h.insert(AUTHORIZATION, format!("Bearer {token}").parse().unwrap());
        h
    }

    #[test]
    fn valid_token_yields_sub() {
        let t = make_token("user-123", 3600);
        assert_eq!(require_user_id(&bearer(&t), SECRET).ok().as_deref(), Some("user-123"));
    }

    #[test]
    fn expired_token_rejected() {
        // -3600 is well past the crate's default 60s leeway.
        let t = make_token("user-123", -3600);
        assert!(require_user_id(&bearer(&t), SECRET).is_err());
    }

    #[test]
    fn wrong_secret_rejected() {
        let t = token_signed_with(Algorithm::HS256, "user-123", 3600, "a-different-secret");
        assert!(require_user_id(&bearer(&t), SECRET).is_err());
    }

    #[test]
    fn non_hs256_algorithm_rejected() {
        // Valid signature, correct secret, but signed with HS384 -- the
        // headline property: Validation::default() pins HS256, so a token
        // asserting any other algorithm must be rejected. Guards against
        // an alg-confusion regression if the accepted set is ever widened.
        let t = token_signed_with(Algorithm::HS384, "admin", 3600, SECRET);
        assert!(require_user_id(&bearer(&t), SECRET).is_err());
    }

    #[test]
    fn missing_bearer_prefix_rejected() {
        let t = make_token("user-123", 3600);
        let mut h = HeaderMap::new();
        h.insert(AUTHORIZATION, t.parse().unwrap()); // no "Bearer " prefix
        assert!(require_user_id(&h, SECRET).is_err());
    }

    #[test]
    fn no_auth_header_falls_through_to_none() {
        assert!(extract_user_id(&HeaderMap::new(), SECRET).is_none());
        assert!(require_user_id(&HeaderMap::new(), SECRET).is_err());
    }

    #[test]
    fn query_param_path_matches_header_path() {
        let t = make_token("ws-user", 3600);
        assert_eq!(require_user_id_from_query(Some(&t), SECRET).ok().as_deref(), Some("ws-user"));
        assert!(require_user_id_from_query(None, SECRET).is_err());
        // An expired token is rejected on the WS path too, not just the header path.
        let expired = make_token("ws-user", -3600);
        assert!(require_user_id_from_query(Some(&expired), SECRET).is_err());
    }
}
