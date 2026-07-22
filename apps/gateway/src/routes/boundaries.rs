use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::QueryBuilder;
use uuid::Uuid;

use crate::{error::AppError, state::AppState};

/// Point-in-polygon / choropleth read path over research_entity_boundaries
/// (0010_entity_boundaries.sql) -- census-tract and zoning polygons,
/// distinct from research_entities' point-only geom (see that migration's
/// comment for why boundaries live in their own table).
#[derive(Debug, Deserialize)]
pub struct BoundariesQuery {
    pub boundary_type: Option<String>,
    /// "min_lon,min_lat,max_lon,max_lat" -- features intersecting this
    /// envelope are returned.
    pub bbox: Option<String>,
    pub limit: Option<i64>,
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct BoundaryResult {
    pub id: Uuid,
    pub name: String,
    pub boundary_type: String,
    pub source: String,
    pub license: Option<String>,
    pub geometry: Value,
    pub retrieved_at: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Serialize)]
pub struct BoundariesResponse {
    pub results: Vec<BoundaryResult>,
    pub count: usize,
}

fn parse_bbox(bbox: &str) -> Result<(f64, f64, f64, f64), AppError> {
    let parts: Vec<&str> = bbox.split(',').collect();
    if parts.len() != 4 {
        return Err(AppError::BadRequest(
            "bbox must be \"min_lon,min_lat,max_lon,max_lat\"".to_string(),
        ));
    }
    let mut values = [0.0f64; 4];
    for (i, part) in parts.iter().enumerate() {
        values[i] = part
            .trim()
            .parse::<f64>()
            .map_err(|_| AppError::BadRequest("bbox values must be numbers".to_string()))?;
    }
    let (min_lon, min_lat, max_lon, max_lat) = (values[0], values[1], values[2], values[3]);
    if min_lon >= max_lon || min_lat >= max_lat {
        return Err(AppError::BadRequest(
            "bbox min_lon/min_lat must be less than max_lon/max_lat".to_string(),
        ));
    }
    Ok((min_lon, min_lat, max_lon, max_lat))
}

pub async fn list_boundaries(
    State(state): State<AppState>,
    axum::extract::Query(params): axum::extract::Query<BoundariesQuery>,
) -> Result<Json<BoundariesResponse>, AppError> {
    let limit = params.limit.unwrap_or(500).clamp(1, 5000);

    let mut qb: QueryBuilder<sqlx::Postgres> = QueryBuilder::new(
        r#"
        SELECT
            id, name, boundary_type, source, license,
            ST_AsGeoJSON(geom)::json AS geometry,
            retrieved_at
        FROM research_entity_boundaries
        WHERE 1=1
        "#,
    );

    if let Some(boundary_type) = &params.boundary_type {
        qb.push(" AND boundary_type = ");
        qb.push_bind(boundary_type.clone());
    }

    if let Some(bbox) = &params.bbox {
        let (min_lon, min_lat, max_lon, max_lat) = parse_bbox(bbox)?;
        qb.push(" AND ST_Intersects(geom, ST_MakeEnvelope(");
        qb.push_bind(min_lon);
        qb.push(", ");
        qb.push_bind(min_lat);
        qb.push(", ");
        qb.push_bind(max_lon);
        qb.push(", ");
        qb.push_bind(max_lat);
        qb.push(", 4326))");
    }

    qb.push(" LIMIT ");
    qb.push_bind(limit);

    let results: Vec<BoundaryResult> = qb.build_query_as().fetch_all(&state.db).await?;
    let count = results.len();

    Ok(Json(BoundariesResponse { results, count }))
}
