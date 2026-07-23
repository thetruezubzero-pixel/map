use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Query, State,
    },
    response::Response,
};
use serde::Deserialize;
use serde_json::Value;
use sqlx::postgres::PgListener;
use uuid::Uuid;

use crate::{middleware::auth::require_user_id_from_query, state::AppState};

#[derive(Debug, Deserialize)]
pub struct WsAuthQuery {
    pub token: Option<String>,
}

#[derive(Debug, sqlx::FromRow, serde::Serialize)]
struct AlertRow {
    id: Uuid,
    subscription_id: Uuid,
    user_id: String,
    severity: String,
    title: String,
    description: String,
    source_topic: String,
    source_event_id: Option<String>,
    entity_id: Option<String>,
    lat: Option<f64>,
    lon: Option<f64>,
    channels: Vec<String>,
    created_at: chrono::DateTime<chrono::Utc>,
}

/// Real-time alert stream for the authenticated user. Alerts are
/// delivered here the moment
/// `apps/api/python/app/streaming/producers/alert_dispatcher.py` INSERTs
/// a matching row into Postgres `user_alerts` -- that INSERT fires a
/// `pg_notify('user_alerts_channel', ...)` trigger
/// (migrations/0007_alerts.sql), and this handler holds a `PgListener`
/// on that channel for the lifetime of the WebSocket connection.
///
/// Auth is via `?token=<jwt>` (query param, not the Authorization header
/// -- see `require_user_id_from_query`'s doc comment for why and its
/// tradeoff) since this is not behind the rate-limit middleware's header
/// check and browsers can't set custom headers on a WS handshake.
pub async fn ws_alerts(
    State(state): State<AppState>,
    Query(query): Query<WsAuthQuery>,
    ws: WebSocketUpgrade,
) -> Result<Response, crate::error::AppError> {
    let user_id = require_user_id_from_query(query.token.as_deref(), &state.config.jwt_secret)?;

    // Cap total concurrent /ws/alerts connections process-wide: each one
    // holds a dedicated PgListener connection for its whole lifetime, so
    // without this a single valid JWT could open enough to exhaust
    // Postgres connection slots. The permit is moved into handle_socket
    // and released automatically when the connection ends (Drop).
    let Ok(permit) = state.ws_alerts_semaphore.clone().try_acquire_owned() else {
        return Err(crate::error::AppError::ServiceUnavailable(
            "alert stream at capacity -- try again shortly".to_string(),
        ));
    };
    Ok(ws.on_upgrade(move |socket| handle_socket(socket, state, user_id, permit)))
}

async fn handle_socket(
    mut socket: WebSocket,
    state: AppState,
    user_id: String,
    _permit: tokio::sync::OwnedSemaphorePermit,
) {
    // `PgListener::connect_with(&state.db)` would pull a real connection out
    // of the shared pool (max_connections=10) and hold it for this socket's
    // entire lifetime -- confirmed live that ~10 concurrent WS connections
    // from one valid JWT starves every other DB-backed route (/health,
    // /search, /subscriptions, ...) gateway-wide. `connect()` opens a
    // dedicated connection outside the shared pool instead.
    let mut listener = match PgListener::connect(&state.config.database_url).await {
        Ok(l) => l,
        Err(err) => {
            tracing::error!("ws_alerts: failed to open PgListener: {err}");
            let _ = socket
                .send(Message::Text(
                    serde_json::json!({"error": "alert stream unavailable"}).to_string(),
                ))
                .await;
            return;
        }
    };

    if let Err(err) = listener.listen("user_alerts_channel").await {
        tracing::error!("ws_alerts: LISTEN failed: {err}");
        return;
    }

    let _ = socket
        .send(Message::Text(
            serde_json::json!({"type": "connected", "user_id": user_id}).to_string(),
        ))
        .await;

    loop {
        tokio::select! {
            notification = listener.recv() => {
                let notification = match notification {
                    Ok(n) => n,
                    Err(err) => {
                        tracing::warn!("ws_alerts: listener error, closing: {err}");
                        break;
                    }
                };

                let payload: Value = match serde_json::from_str(notification.payload()) {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                let Some(notified_user) = payload.get("user_id").and_then(|v| v.as_str()) else { continue };
                if notified_user != user_id {
                    continue; // not for this connection -- see migration's NOTIFY comment
                }
                let Some(alert_id) = payload.get("id").and_then(|v| v.as_str()).and_then(|s| s.parse::<Uuid>().ok()) else { continue };

                let row = sqlx::query_as::<_, AlertRow>(
                    r#"
                    SELECT id, subscription_id, user_id, severity, title, description,
                           source_topic, source_event_id, entity_id, lat, lon, channels, created_at
                    FROM user_alerts WHERE id = $1
                    "#,
                )
                .bind(alert_id)
                .fetch_optional(&state.db)
                .await;

                match row {
                    Ok(Some(alert)) => {
                        let text = serde_json::to_string(&alert).unwrap_or_default();
                        if socket.send(Message::Text(text)).await.is_err() {
                            break;
                        }
                    }
                    Ok(None) => {}
                    Err(err) => tracing::warn!("ws_alerts: failed to fetch alert {alert_id}: {err}"),
                }
            }
            incoming = socket.recv() => {
                match incoming {
                    Some(Ok(Message::Close(_))) | None => break,
                    Some(Err(_)) => break,
                    _ => {} // ignore client pings/other frames
                }
            }
        }
    }
}
