-- Phase 1: base schema
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    geom GEOMETRY(Point, 4326) NOT NULL,
    source TEXT NOT NULL,
    license TEXT,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS locations_geom_idx ON locations USING GIST (geom);

CREATE TABLE IF NOT EXISTS research_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source TEXT NOT NULL,
    license TEXT,
    geom GEOMETRY(Point, 4326),
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS research_entities_geom_idx ON research_entities USING GIST (geom);
CREATE INDEX IF NOT EXISTS research_entities_type_idx ON research_entities (entity_type);
CREATE INDEX IF NOT EXISTS research_entities_source_idx ON research_entities (source);
