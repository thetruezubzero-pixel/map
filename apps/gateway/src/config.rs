use std::env;

#[derive(Clone)]
pub struct Config {
    pub bind_addr: String,
    pub database_url: String,
    pub allowed_origins: Vec<String>,
    pub nominatim_base_url: String,
    pub nominatim_user_agent: String,
    pub nominatim_api_key: Option<String>,
    pub jwt_secret: String,
    pub python_api_base_url: String,
    pub rate_limit_burst: u32,
    pub rate_limit_per_sec: u32,
    pub authed_rate_limit_per_sec: u32,
}

impl Config {
    pub fn from_env() -> Self {
        dotenvy::dotenv().ok();

        let allowed_origins = env::var("ALLOWED_ORIGINS")
            .unwrap_or_else(|_| "http://localhost:5173".to_string())
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        Self {
            bind_addr: env::var("GATEWAY_BIND_ADDR").unwrap_or_else(|_| "0.0.0.0:8080".to_string()),
            database_url: env::var("DATABASE_URL")
                .unwrap_or_else(|_| "postgres://aether:aether@localhost:5432/aether".to_string()),
            allowed_origins,
            nominatim_base_url: env::var("NOMINATIM_BASE_URL")
                .unwrap_or_else(|_| "https://nominatim.openstreetmap.org".to_string()),
            nominatim_user_agent: env::var("NOMINATIM_USER_AGENT")
                .unwrap_or_else(|_| "AetherSovereignOS/0.2 (contact: set NOMINATIM_USER_AGENT)".to_string()),
            nominatim_api_key: env::var("NOMINATIM_API_KEY").ok(),
            jwt_secret: env::var("JWT_SECRET").unwrap_or_else(|_| "dev-only-insecure-secret".to_string()),
            python_api_base_url: env::var("PYTHON_API_BASE_URL")
                .unwrap_or_else(|_| "http://localhost:8000".to_string()),
            rate_limit_burst: env::var("RATE_LIMIT_BURST")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(10),
            rate_limit_per_sec: env::var("RATE_LIMIT_PER_SEC")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(1),
            authed_rate_limit_per_sec: env::var("AUTHED_RATE_LIMIT_PER_SEC")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(5),
        }
    }
}
