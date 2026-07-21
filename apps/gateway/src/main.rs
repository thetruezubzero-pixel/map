mod config;
mod db;
mod error;
mod middleware;
mod routes;
mod state;

use std::net::SocketAddr;

use axum::{
    http::{header, Method},
    middleware::from_fn_with_state,
    routing::{get, post},
    Router,
};
use tower_http::{
    cors::{AllowOrigin, CorsLayer},
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
        .allow_methods([Method::GET, Method::POST])
        .allow_headers([header::CONTENT_TYPE, header::AUTHORIZATION]);

    let state = AppState::new(config, db);

    let rate_limited = Router::new()
        .route("/geocode", get(routes::geocode::geocode))
        .route("/search", get(routes::search::search))
        .route("/entities/:id", get(routes::entities::get_entity))
        .route("/research", post(routes::research::create_research_job))
        .route_layer(from_fn_with_state(state.clone(), middleware::rate_limit::rate_limit));

    let app = Router::new()
        .route("/health", get(routes::health::health))
        .merge(rate_limited)
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
