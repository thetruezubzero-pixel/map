use axum::{extract::State, Json};
use serde_json::{json, Value};

use crate::state::AppState;

pub async fn health(State(state): State<AppState>) -> Json<Value> {
    let db_ok = sqlx::query("SELECT 1").execute(&state.db).await.is_ok();

    Json(json!({
        "status": if db_ok { "ok" } else { "degraded" },
        "service": "aether-gateway",
        "version": env!("CARGO_PKG_VERSION"),
        "db": db_ok,
    }))
}
