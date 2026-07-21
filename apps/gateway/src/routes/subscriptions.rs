use axum::{
    extract::{Path, State},
    http::HeaderMap,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{error::AppError, middleware::auth::require_user_id, state::AppState};

const SUBSCRIPTION_TYPES: [&str; 4] = ["entity", "keyword", "geofence", "composite"];
const SEVERITIES: [&str; 3] = ["INFO", "WARNING", "CRITICAL"];

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct Subscription {
    pub id: Uuid,
    pub user_id: String,
    pub subscription_type: String,
    pub criteria: Value,
    pub min_severity: String,
    pub channels: Vec<String>,
    pub webhook_url: Option<String>,
    pub is_active: bool,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Deserialize)]
pub struct CreateSubscriptionRequest {
    pub subscription_type: String,
    #[serde(default = "default_criteria")]
    pub criteria: Value,
    #[serde(default = "default_severity")]
    pub min_severity: String,
    #[serde(default = "default_channels")]
    pub channels: Vec<String>,
    pub webhook_url: Option<String>,
}

fn default_criteria() -> Value {
    serde_json::json!({})
}
fn default_severity() -> String {
    "INFO".to_string()
}
fn default_channels() -> Vec<String> {
    vec!["in_app".to_string()]
}

#[derive(Debug, Deserialize)]
pub struct UpdateSubscriptionRequest {
    pub criteria: Option<Value>,
    pub min_severity: Option<String>,
    pub channels: Option<Vec<String>>,
    pub webhook_url: Option<String>,
    pub is_active: Option<bool>,
}

fn validate_type(subscription_type: &str) -> Result<(), AppError> {
    if !SUBSCRIPTION_TYPES.contains(&subscription_type) {
        return Err(AppError::BadRequest(format!(
            "subscription_type must be one of {:?}",
            SUBSCRIPTION_TYPES
        )));
    }
    Ok(())
}

fn validate_severity(severity: &str) -> Result<(), AppError> {
    if !SEVERITIES.contains(&severity) {
        return Err(AppError::BadRequest(format!(
            "min_severity must be one of {:?}",
            SEVERITIES
        )));
    }
    Ok(())
}

pub async fn create_subscription(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<CreateSubscriptionRequest>,
) -> Result<Json<Subscription>, AppError> {
    let user_id = require_user_id(&headers, &state.config.jwt_secret)?;
    validate_type(&payload.subscription_type)?;
    validate_severity(&payload.min_severity)?;

    let sub = sqlx::query_as::<_, Subscription>(
        r#"
        INSERT INTO user_subscriptions
            (user_id, subscription_type, criteria, min_severity, channels, webhook_url)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, user_id, subscription_type, criteria, min_severity, channels,
                  webhook_url, is_active, created_at, updated_at
        "#,
    )
    .bind(&user_id)
    .bind(&payload.subscription_type)
    .bind(&payload.criteria)
    .bind(&payload.min_severity)
    .bind(&payload.channels)
    .bind(&payload.webhook_url)
    .fetch_one(&state.db)
    .await?;

    Ok(Json(sub))
}

pub async fn list_subscriptions(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Vec<Subscription>>, AppError> {
    let user_id = require_user_id(&headers, &state.config.jwt_secret)?;

    let subs = sqlx::query_as::<_, Subscription>(
        r#"
        SELECT id, user_id, subscription_type, criteria, min_severity, channels,
               webhook_url, is_active, created_at, updated_at
        FROM user_subscriptions
        WHERE user_id = $1
        ORDER BY created_at DESC
        "#,
    )
    .bind(&user_id)
    .fetch_all(&state.db)
    .await?;

    Ok(Json(subs))
}

pub async fn get_subscription(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<Json<Subscription>, AppError> {
    let user_id = require_user_id(&headers, &state.config.jwt_secret)?;

    let sub = sqlx::query_as::<_, Subscription>(
        r#"
        SELECT id, user_id, subscription_type, criteria, min_severity, channels,
               webhook_url, is_active, created_at, updated_at
        FROM user_subscriptions
        WHERE id = $1 AND user_id = $2
        "#,
    )
    .bind(id)
    .bind(&user_id)
    .fetch_optional(&state.db)
    .await?
    .ok_or(AppError::NotFound)?;

    Ok(Json(sub))
}

pub async fn update_subscription(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
    Json(payload): Json<UpdateSubscriptionRequest>,
) -> Result<Json<Subscription>, AppError> {
    let user_id = require_user_id(&headers, &state.config.jwt_secret)?;
    if let Some(sev) = &payload.min_severity {
        validate_severity(sev)?;
    }

    let sub = sqlx::query_as::<_, Subscription>(
        r#"
        UPDATE user_subscriptions
        SET criteria = COALESCE($3, criteria),
            min_severity = COALESCE($4, min_severity),
            channels = COALESCE($5, channels),
            webhook_url = COALESCE($6, webhook_url),
            is_active = COALESCE($7, is_active),
            updated_at = now()
        WHERE id = $1 AND user_id = $2
        RETURNING id, user_id, subscription_type, criteria, min_severity, channels,
                  webhook_url, is_active, created_at, updated_at
        "#,
    )
    .bind(id)
    .bind(&user_id)
    .bind(&payload.criteria)
    .bind(&payload.min_severity)
    .bind(&payload.channels)
    .bind(&payload.webhook_url)
    .bind(payload.is_active)
    .fetch_optional(&state.db)
    .await?
    .ok_or(AppError::NotFound)?;

    Ok(Json(sub))
}

pub async fn delete_subscription(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(id): Path<Uuid>,
) -> Result<(), AppError> {
    let user_id = require_user_id(&headers, &state.config.jwt_secret)?;

    let result = sqlx::query("DELETE FROM user_subscriptions WHERE id = $1 AND user_id = $2")
        .bind(id)
        .bind(&user_id)
        .execute(&state.db)
        .await?;

    if result.rows_affected() == 0 {
        return Err(AppError::NotFound);
    }
    Ok(())
}
