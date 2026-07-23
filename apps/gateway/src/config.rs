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
    // Total concurrent /ws/alerts connections allowed process-wide. Each
    // one holds a dedicated PgListener connection for its whole lifetime
    // (routes/alerts_ws.rs), so without a cap a single legit JWT could
    // open enough of them to exhaust Postgres connection slots -- a
    // readiness review flagged this as the remaining half of the
    // /ws/alerts resource-exhaustion story (the PgListener-not-from-pool
    // fix addressed pool starvation; this bounds the dedicated
    // connections). Same NonZero-style guard as the timeouts above.
    pub ws_alerts_max_connections: usize,
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
            jwt_secret: {
                let value = env::var("JWT_SECRET").unwrap_or_else(|_| {
                    tracing::warn!(
                        "JWT_SECRET is not set -- falling back to a well-known insecure default. \
                         Tokens signed with it are forgeable. Set JWT_SECRET before deploying anywhere \
                         reachable outside your own machine."
                    );
                    "dev-only-insecure-secret".to_string()
                });
                // A "connect the dots" audit found this check only caught the
                // *missing* case -- but .env.example ships
                // `JWT_SECRET=change-me-in-production` as a literal value, and
                // docker-compose's `${JWT_SECRET:?...}` guard only requires
                // non-empty, not "was actually changed". Anyone who copies the
                // example file verbatim (a natural first step) ends up with a
                // JWT_SECRET that's just as publicly known and forgeable as the
                // old hardcoded default this warning already exists to catch --
                // just via a different well-known string. Same warning, same
                // reasoning, closing the gap the placeholder text left open.
                if value == "change-me-in-production" {
                    tracing::warn!(
                        "JWT_SECRET is still the placeholder value from .env.example \
                         (\"change-me-in-production\") -- this is just as forgeable as never \
                         setting it, since it's a known string in this repo's history. Set a \
                         real random secret before deploying anywhere reachable outside your \
                         own machine."
                    );
                }
                value
            },
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
            // A readiness review found a malformed value here (non-numeric,
            // negative) already safely falls back to the default via
            // `.ok()`, but `HTTP_CLIENT_TIMEOUT_SECS=0`/`REQUEST_TIMEOUT_SECS=0`
            // parses to a valid `0u64` and isn't rejected -- Duration::from_secs(0)
            // makes every request/outbound call time out instantly. The
            // rate-limit quotas just below already guard the equivalent
            // operator-misconfiguration case via NonZeroU32; `.filter(|&v| v > 0)`
            // gives these two the same treatment.
            http_client_timeout_secs: env::var("HTTP_CLIENT_TIMEOUT_SECS")
                .ok()
                .and_then(|v| v.parse::<u64>().ok())
                .filter(|&v| v > 0)
                .unwrap_or(10),
            request_timeout_secs: env::var("REQUEST_TIMEOUT_SECS")
                .ok()
                .and_then(|v| v.parse::<u64>().ok())
                .filter(|&v| v > 0)
                .unwrap_or(30),
            ws_alerts_max_connections: env::var("WS_ALERTS_MAX_CONNECTIONS")
                .ok()
                .and_then(|v| v.parse::<usize>().ok())
                .filter(|&v| v > 0)
                .unwrap_or(50),
        }
    }
}
