mod config;
mod db;
mod error;
mod middleware;
mod routes;
mod state;

use std::net::SocketAddr;
use std::time::Duration;

use axum::{
    http::{header, Method, StatusCode},
    middleware::from_fn_with_state,
    routing::{get, post},
    Router,
};
use tower_http::{
    cors::{AllowOrigin, CorsLayer},
    timeout::TimeoutLayer,
    trace::TraceLayer,
};

use config::Config;
use state::AppState;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "aether_gateway=info,tower_http=info".into()),
        )
        .init();

    let config = Config::from_env();
    let bind_addr: SocketAddr = config.bind_addr.parse()?;

    let db = db::connect(&config.database_url).await?;
    sqlx::migrate!("./migrations").run(&db).await?;

    let allowed_origins: Vec<_> = config
        .allowed_origins
        .iter()
        .filter_map(|o| o.parse::<header::HeaderValue>().ok())
        .collect();

    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::list(allowed_origins))
        .allow_methods([Method::GET, Method::POST, Method::PATCH, Method::DELETE])
        .allow_headers([header::CONTENT_TYPE, header::AUTHORIZATION]);

    let state = AppState::new(config, db);

    // Periodically evict stale entries from both keyed rate limiters --
    // a readiness review found nothing ever called governor's
    // `retain_recent`, so the per-IP/per-user maps grew unbounded for
    // the life of the process.
    let cleanup_state = state.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(300));
        loop {
            interval.tick().await;
            cleanup_state.cleanup_rate_limiters();
        }
    });

    // A readiness review found the router itself had no request timeout
    // despite tower-http's "timeout" feature already being enabled and
    // unused in Cargo.toml. `with_status_code` (unlike the deprecated
    // `TimeoutLayer::new`) responds with a real HTTP response directly,
    // no HandleErrorLayer needed. Deliberately scoped to ordinary
    // request/response routes only -- NOT applied to /ws/alerts below,
    // since a WebSocket connection is meant to stay open indefinitely;
    // a blanket timeout would force-disconnect every alert subscriber
    // after request_timeout_secs, counting the whole connection
    // lifetime as "one request".
    let timeout_layer = TimeoutLayer::with_status_code(
        StatusCode::REQUEST_TIMEOUT,
        Duration::from_secs(state.config.request_timeout_secs),
    );

    let rate_limited = Router::new()
        .route("/geocode", get(routes::geocode::geocode))
        .route("/search", get(routes::search::search))
        .route("/entities/:id", get(routes::entities::get_entity))
        .route("/boundaries", get(routes::boundaries::list_boundaries))
        .route("/research", post(routes::research::create_research_job))
        .route(
            "/subscriptions",
            get(routes::subscriptions::list_subscriptions).post(routes::subscriptions::create_subscription),
        )
        .route(
            "/subscriptions/:id",
            get(routes::subscriptions::get_subscription)
                .patch(routes::subscriptions::update_subscription)
                .delete(routes::subscriptions::delete_subscription),
        )
        .layer(timeout_layer)
        .route_layer(from_fn_with_state(state.clone(), middleware::rate_limit::rate_limit));

    // /ws/alerts previously had no rate/connection limit of its own
    // (registered directly on `app`, outside any rate-limited group) --
    // a readiness review flagged that a burst of WS upgrade attempts
    // from one IP/user had nothing throttling it. Same per-IP/per-user
    // limiter every other route already uses, kept in its own router so
    // it stays outside `timeout_layer` above (see that comment).
    let ws_routes = Router::new()
        .route("/ws/alerts", get(routes::alerts_ws::ws_alerts))
        .route_layer(from_fn_with_state(state.clone(), middleware::rate_limit::rate_limit));

    let app = Router::new()
        .route("/health", get(routes::health::health))
        .route("/health/streaming", get(routes::health_streaming::health_streaming))
        .merge(rate_limited)
        .merge(ws_routes)
        .layer(cors)
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    tracing::info!("aether-gateway listening on {}", bind_addr);
    let listener = tokio::net::TcpListener::bind(bind_addr).await?;
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await?;

    Ok(())
}
