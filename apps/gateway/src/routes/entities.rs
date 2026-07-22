use axum::{extract::{Path, State}, Json};
use serde::Serialize;
use serde_json::Value;
use uuid::Uuid;

use crate::{error::AppError, state::AppState};

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct EntityDetail {
    pub id: Uuid,
    pub name: String,
    pub entity_type: String,
    pub source: String,
    pub license: Option<String>,
    pub lon: Option<f64>,
    pub lat: Option<f64>,
    pub retrieved_at: chrono::DateTime<chrono::Utc>,
    pub metadata: Value,
}

/// Structured public-record retrieval for a single entity. Entities
/// represent public records only (business registrations, OSM POIs,
/// public news mentions) -- see ROADMAP.md for scope boundaries.
pub async fn get_entity(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<EntityDetail>, AppError> {
    let entity = sqlx::query_as::<_, EntityDetail>(
        r#"
        SELECT
            id, name, entity_type, source, license,
            ST_X(geom::geometry) AS lon,
            ST_Y(geom::geometry) AS lat,
            retrieved_at,
            metadata
        FROM research_entities
        WHERE id = $1
        "#,
    )
    .bind(id)
    .fetch_optional(&state.db)
    .await?
    .ok_or(AppError::NotFound)?;

    Ok(Json(entity))
}
