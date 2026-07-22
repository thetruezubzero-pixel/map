use axum::{extract::State, Json};
use chrono::NaiveDate;
use serde::{Deserialize, Serialize};
use sqlx::QueryBuilder;
use uuid::Uuid;

use crate::{error::AppError, state::AppState};

#[derive(Debug, Deserialize)]
pub struct SearchQuery {
    /// Free-text query, matched against the entity full-text search vector.
    pub q: Option<String>,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    /// Search radius in meters, requires lat/lon.
    pub radius_m: Option<f64>,
    pub source: Option<String>,
    pub entity_type: Option<String>,
    pub date_from: Option<NaiveDate>,
    pub date_to: Option<NaiveDate>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct SearchResult {
    pub id: Uuid,
    pub name: String,
    pub entity_type: String,
    pub source: String,
    pub license: Option<String>,
    pub lon: Option<f64>,
    pub lat: Option<f64>,
    pub distance_m: Option<f64>,
    pub retrieved_at: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Serialize)]
pub struct SearchResponse {
    pub results: Vec<SearchResult>,
    pub count: usize,
}

pub async fn search(
    State(state): State<AppState>,
    axum::extract::Query(params): axum::extract::Query<SearchQuery>,
) -> Result<Json<SearchResponse>, AppError> {
    let limit = params.limit.unwrap_or(25).clamp(1, 200);
    let offset = params.offset.unwrap_or(0).max(0);

    let point = match (params.lat, params.lon) {
        (Some(lat), Some(lon)) => Some((lat, lon)),
        _ => None,
    };

    let mut qb: QueryBuilder<sqlx::Postgres> = QueryBuilder::new(
        r#"
        SELECT
            e.id,
            e.name,
            e.entity_type,
            e.source,
            e.license,
            ST_X(e.geom::geometry) AS lon,
            ST_Y(e.geom::geometry) AS lat,
        "#,
    );

    if let (Some(lat), Some(lon)) = (params.lat, params.lon) {
        qb.push("ST_Distance(e.geom::geography, ST_SetSRID(ST_MakePoint(");
        qb.push_bind(lon);
        qb.push(", ");
        qb.push_bind(lat);
        qb.push("), 4326)::geography) AS distance_m,");
    } else {
        qb.push("NULL::float8 AS distance_m,");
    }

    qb.push(" e.retrieved_at FROM research_entities e WHERE 1=1");

    if let Some(q) = &params.q {
        if !q.trim().is_empty() {
            qb.push(" AND e.search_vector @@ plainto_tsquery('english', ");
            qb.push_bind(q.clone());
            qb.push(")");
        }
    }

    if let Some(source) = &params.source {
        qb.push(" AND e.source = ");
        qb.push_bind(source.clone());
    }

    if let Some(entity_type) = &params.entity_type {
        qb.push(" AND e.entity_type = ");
        qb.push_bind(entity_type.clone());
    }

    if let Some(date_from) = params.date_from {
        qb.push(" AND e.retrieved_at >= ");
        qb.push_bind(date_from);
    }

    if let Some(date_to) = params.date_to {
        qb.push(" AND e.retrieved_at <= ");
        qb.push_bind(date_to);
    }

    if let Some((lat, lon)) = point {
        let radius = params.radius_m.unwrap_or(5000.0);
        qb.push(" AND ST_DWithin(e.geom::geography, ST_SetSRID(ST_MakePoint(");
        qb.push_bind(lon);
        qb.push(", ");
        qb.push_bind(lat);
        qb.push("), 4326)::geography, ");
        qb.push_bind(radius);
        qb.push(")");
        qb.push(" ORDER BY distance_m ASC");
    } else if params.q.is_some() {
        qb.push(" ORDER BY ts_rank(e.search_vector, plainto_tsquery('english', ");
        qb.push_bind(params.q.clone().unwrap_or_default());
        qb.push(")) DESC");
    } else {
        qb.push(" ORDER BY e.retrieved_at DESC");
    }

    qb.push(" LIMIT ");
    qb.push_bind(limit);
    qb.push(" OFFSET ");
    qb.push_bind(offset);

    let results: Vec<SearchResult> = qb.build_query_as().fetch_all(&state.db).await?;
    let count = results.len();

    Ok(Json(SearchResponse { results, count }))
}
