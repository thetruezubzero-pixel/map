mod handlers;
mod middleware;

use std::env;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use axum::http::{HeaderValue, Method};
use axum::routing::get;
use axum::Router;
use tower_governor::governor::GovernorConfigBuilder;
use tower_governor::key_extractor::SmartIpKeyExtractor;
use tower_governor::GovernorLayer;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;

pub struct AppState {
    pub http_client: reqwest::Client,
    pub nominatim_base_url: String,
}

fn cors_layer() -> CorsLayer {
    let origins = env::var("CORS_ALLOWED_ORIGINS").unwrap_or_default();
    let allowed: Vec<HeaderValue> = origins
        .split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .filter_map(|s| s.parse().ok())
        .collect();

    if allowed.is_empty() {
        // No origins configured: allow same-origin/non-browser clients only,
        // reject all cross-origin browser requests by default.
        CorsLayer::new().allow_methods([Method::GET])
    } else {
        CorsLayer::new()
            .allow_origin(allowed)
            .allow_methods([Method::GET])
    }
}

fn rate_limit_layer() -> GovernorLayer<SmartIpKeyExtractor, governor::middleware::NoOpMiddleware> {
    let per_second: u64 = env::var("RATE_LIMIT_PER_SECOND")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(2);
    let burst: u32 = env::var("RATE_LIMIT_BURST")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(10);

    let config = Arc::new(
        GovernorConfigBuilder::default()
            .key_extractor(SmartIpKeyExtractor)
            .per_second(per_second)
            .burst_size(burst)
            .finish()
            .expect("valid rate limit configuration"),
    );

    // Periodically evict stale rate-limit entries so memory doesn't grow unbounded.
    let cleanup_config = config.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(60));
        loop {
            interval.tick().await;
            cleanup_config.limiter().retain_recent();
        }
    });

    GovernorLayer { config }
}

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "aether_gateway=info,tower_http=info".into()),
        )
        .init();

    let nominatim_base_url = env::var("NOMINATIM_BASE_URL")
        .unwrap_or_else(|_| "https://nominatim.openstreetmap.org".to_string());

    let http_client = reqwest::Client::builder()
        .user_agent("aether-sovereign-os-gateway/0.1 (contact: set OPERATOR_CONTACT env var)")
        .timeout(Duration::from_secs(10))
        .build()
        .expect("failed to build HTTP client");

    let state = Arc::new(AppState {
        http_client,
        nominatim_base_url,
    });

    let app = Router::new()
        .route("/health", get(handlers::health::health))
        .route("/geocode", get(handlers::geocode::geocode))
        .layer(axum::middleware::from_fn(
            middleware::bot_detection::reject_suspicious_requests,
        ))
        .layer(rate_limit_layer())
        .layer(cors_layer())
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    let port: u16 = env::var("PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8080);
    let addr = SocketAddr::from(([0, 0, 0, 0], port));

    tracing::info!("aether-gateway listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("failed to bind address");
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await
    .expect("server error");
}
