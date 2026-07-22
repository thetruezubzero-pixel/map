-- Phase 6: census-tract/zoning polygon ingestion -- unlocks real spatial
-- joins (point-in-polygon) and choropleth rendering, per ROADMAP.md's
-- Phase 6.
--
-- research_entities.geom is Point-only (0001_init.sql) by design -- every
-- existing source (census_tiger_dag, fema_flood_hazard_dag) already works
-- around that by storing a seed-point lookup against an upstream polygon
-- service rather than the polygon itself (see their docstrings). A real
-- polygon column belongs in its own table rather than widening
-- research_entities' geom type, since boundary rows are areal reference
-- data (a tract or zoning district), not point entities that /search's
-- ST_Distance/ST_DWithin logic reasons about.
CREATE TABLE IF NOT EXISTS research_entity_boundaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    boundary_type TEXT NOT NULL CHECK (boundary_type IN ('census_tract', 'zoning')),
    source TEXT NOT NULL,
    license TEXT,
    geom GEOMETRY(MultiPolygon, 4326) NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Idempotency key, same pattern/rationale as research_entities'
-- (source, entity_type, name) constraint in 0004_entities_idempotency.sql
-- -- without it, upsert_boundaries()'s ON CONFLICT DO NOTHING has nothing
-- to conflict against and every DAG re-run duplicates every polygon.
ALTER TABLE research_entity_boundaries
    ADD CONSTRAINT research_entity_boundaries_source_type_name_key
    UNIQUE (source, boundary_type, name);

-- Raw-geometry GIST index for ST_Intersects point-in-polygon spatial
-- joins (no geography cast here, unlike research_entities_geog_idx --
-- containment queries don't need meter-accurate distance, only exact
-- polygon topology, which the geometry operator class serves directly).
CREATE INDEX IF NOT EXISTS research_entity_boundaries_geom_idx
    ON research_entity_boundaries USING GIST (geom);

CREATE INDEX IF NOT EXISTS research_entity_boundaries_type_idx
    ON research_entity_boundaries (boundary_type);
