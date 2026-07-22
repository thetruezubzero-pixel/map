-- Phase 2: full-text search, entity relationship graph, research jobs, audit log.
--
-- Scope guardrail: research_entities.entity_type is restricted to public
-- record categories. Individual/person profiling is out of scope for this
-- platform (see ROADMAP.md) and is enforced here at the schema level.
ALTER TABLE research_entities
    ADD CONSTRAINT research_entities_type_allowlist
    CHECK (entity_type IN ('business', 'government_filing', 'location', 'poi', 'news_mention'));

ALTER TABLE research_entities ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE OR REPLACE FUNCTION research_entities_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', coalesce(NEW.name, '') || ' ' || coalesce(NEW.entity_type, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS research_entities_search_vector_trigger ON research_entities;
CREATE TRIGGER research_entities_search_vector_trigger
    BEFORE INSERT OR UPDATE ON research_entities
    FOR EACH ROW EXECUTE FUNCTION research_entities_search_vector_update();

CREATE INDEX IF NOT EXISTS research_entities_search_vector_idx ON research_entities USING GIN (search_vector);

-- Corporate parent/subsidiary graph only (business entities). Not used for
-- personal relationship mapping.
CREATE TABLE IF NOT EXISTS entity_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_entity_id UUID NOT NULL REFERENCES research_entities(id) ON DELETE CASCADE,
    child_entity_id UUID NOT NULL REFERENCES research_entities(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'subsidiary',
    source TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (parent_entity_id, child_entity_id, relation_type)
);

CREATE TABLE IF NOT EXISTS research_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query TEXT NOT NULL,
    requested_by TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    result JSONB,
    requires_review BOOLEAN NOT NULL DEFAULT true,
    reviewed_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS research_jobs_status_idx ON research_jobs (status);

-- Append-only audit trail for all agent actions.
CREATE TABLE IF NOT EXISTS agent_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES research_jobs(id) ON DELETE SET NULL,
    agent_name TEXT NOT NULL,
    action TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION agent_audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'agent_audit_log is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS agent_audit_log_no_update ON agent_audit_log;
CREATE TRIGGER agent_audit_log_no_update
    BEFORE UPDATE OR DELETE ON agent_audit_log
    FOR EACH ROW EXECUTE FUNCTION agent_audit_log_immutable();
