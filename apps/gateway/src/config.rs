use std::env;

#[derive(Clone)]
pub struct Config {
    pub bind_addr: String,
    pub database_url: String,
    pub allowed_origins: Vec<String>,
    pub nominatim_base_url: String,
    pub nominatim_user_agent: String,
    pub nominatim_api_key: Option<String>,
    pub photon_base_url: String,
    pub jwt_secret: String,
    pub python_api_base_url: String,
    pub rate_limit_burst: u32,
    pub rate_limit_per_sec: u32,
    pub authed_rate_limit_per_sec: u32,
    // A readiness review found the outbound reqwest::Client (geocode.rs/
    // research.rs) and the axum router itself had no timeout at all --
    // tower-http's "timeout" feature was already enabled in Cargo.toml
    // but never wired up. A hung upstream (Nominatim/Photon/python-api)
    // could otherwise hold a request open indefinitely.
    pub http_client_timeout_secs: u64,
    pub request_timeout_secs: u64,
    pub kafka_bootstrap_servers: String,
    pub schema_registry_url: String,
    pub ksqldb_url: String,
    pub flink_rest_url: String,
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
            // Fallback geocoder -- Nominatim rate-limits/blocks aggressively
            // per its usage policy (confirmed live: this sandbox's shared
            // egress IP gets a flat 403 regardless of User-Agent), and it's
            // the only geocoder this gateway had, so any Nominatim outage
            // or block took /geocode down entirely. Photon is a separate,
            // independently-run, keyless public instance over the same OSM
            // data (https://photon.komoot.io) -- not affiliated with
            // Nominatim, so a block/outage on one doesn't take down both.
            photon_base_url: env::var("PHOTON_BASE_URL")
                .unwrap_or_else(|_| "https://photon.komoot.io/api".to_string()),
            jwt_secret: env::var("JWT_SECRET").unwrap_or_else(|_| {
                tracing::warn!(
                    "JWT_SECRET is not set -- falling back to a well-known insecure default. \
                     Tokens signed with it are forgeable. Set JWT_SECRET before deploying anywhere \
                     reachable outside your own machine."
                );
                "dev-only-insecure-secret".to_string()
            }),
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
            kafka_bootstrap_servers: env::var("KAFKA_BOOTSTRAP_SERVERS")
                .unwrap_or_else(|_| "localhost:9092".to_string()),
            schema_registry_url: env::var("SCHEMA_REGISTRY_URL")
                .unwrap_or_else(|_| "http://localhost:8082".to_string()),
            ksqldb_url: env::var("KSQLDB_URL").unwrap_or_else(|_| "http://localhost:8088".to_string()),
            flink_rest_url: env::var("FLINK_REST_URL")
                .unwrap_or_else(|_| "http://localhost:8081".to_string()),
            http_client_timeout_secs: env::var("HTTP_CLIENT_TIMEOUT_SECS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(10),
            request_timeout_secs: env::var("REQUEST_TIMEOUT_SECS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(30),
        }
    }
}
