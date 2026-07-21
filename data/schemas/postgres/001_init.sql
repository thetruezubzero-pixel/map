-- Phase 1 baseline schema for Aether Sovereign OS.
-- Only what's needed to back later research/mapping phases; no
-- speculative tables for subsystems that aren't built yet.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- A geocoded point of interest on the map (address, POI, or research target).
CREATE TABLE IF NOT EXISTS locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label TEXT NOT NULL,
    address TEXT,
    geom GEOGRAPHY(POINT, 4326) NOT NULL,
    source TEXT NOT NULL,
    source_retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS locations_geom_idx ON locations USING GIST (geom);

-- A public-records research subject tied to a location (property, business
-- registration, permit, etc.), always attributed to its public source.
CREATE TABLE IF NOT EXISTS research_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    location_id UUID REFERENCES locations (id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL,
    source_url TEXT,
    source_retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS research_entities_location_id_idx ON research_entities (location_id);
CREATE INDEX IF NOT EXISTS research_entities_entity_type_idx ON research_entities (entity_type);
