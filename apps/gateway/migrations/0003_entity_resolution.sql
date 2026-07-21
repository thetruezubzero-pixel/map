-- Phase 3: entity resolution -- cross-source dedup keys, normalized name
-- for fuzzy matching, and a confidence-scored review queue.
--
-- Scope guardrail: this migration adds NO new entity_type value and NO
-- person-like table. Officer/director names surfaced by SEC Form 4 /
-- OpenCorporates stay inside research_entities.metadata on the *company*
-- record (e.g. metadata->'officers') -- they are never promoted to their
-- own row here. See ROADMAP.md.

ALTER TABLE research_entities ADD COLUMN IF NOT EXISTS normalized_name TEXT;
ALTER TABLE research_entities ADD COLUMN IF NOT EXISTS cik TEXT;
ALTER TABLE research_entities ADD COLUMN IF NOT EXISTS opencorporates_id TEXT;
ALTER TABLE research_entities ADD COLUMN IF NOT EXISTS ein TEXT;

CREATE INDEX IF NOT EXISTS research_entities_normalized_name_idx ON research_entities (normalized_name);
CREATE INDEX IF NOT EXISTS research_entities_cik_idx ON research_entities (cik) WHERE cik IS NOT NULL;
CREATE INDEX IF NOT EXISTS research_entities_opencorporates_id_idx ON research_entities (opencorporates_id) WHERE opencorporates_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS research_entities_ein_idx ON research_entities (ein) WHERE ein IS NOT NULL;

-- Candidate matches produced by the resolution pipeline
-- (apps/api/python/app/graph/resolve.py). Confidence >= 0.8 is written
-- straight to entity_relationships (relation_type='same_as'); anything
-- below that lands here for a human to confirm or reject.
CREATE TABLE IF NOT EXISTS entity_resolution_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_a_id UUID NOT NULL REFERENCES research_entities(id) ON DELETE CASCADE,
    entity_b_id UUID NOT NULL REFERENCES research_entities(id) ON DELETE CASCADE,
    confidence NUMERIC(4,3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    match_basis JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending_review' CHECK (status IN ('pending_review', 'confirmed', 'rejected')),
    reviewed_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    CHECK (entity_a_id <> entity_b_id),
    UNIQUE (entity_a_id, entity_b_id)
);

CREATE INDEX IF NOT EXISTS entity_resolution_candidates_status_idx ON entity_resolution_candidates (status);
