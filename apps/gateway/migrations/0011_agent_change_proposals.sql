-- Phase 5c: agents may propose file changes beyond PROJECT_PLAN.md, not
-- just project_architect -- see ROADMAP.md "Phase 5c: widening
-- safe_to_autoimplement" for the full written scope decision this
-- extends (Phase 5b's own text already anticipated this: "the
-- architecture doesn't prevent widening that allowlist ... but that
-- widening is a future, separate decision").
--
-- Safeguards, all enforced in app/agent_swarm/services/change_proposer.py,
-- not left to prompt discipline:
--   - A hard-coded file allowlist (docs/.env.example templates only --
--     never source code, CI config, migrations, or CLAUDE.md/ROADMAP.md,
--     which stay human-owned per the existing Phase 5b norm).
--   - Auto-merge only when confidence * agent_weight clears a threshold,
--     gated behind AGENT_AUTO_MERGE_ENABLED (default off, same
--     kill-switch pattern as ARCHITECT_AUTO_COMMIT_ENABLED).
--   - Every proposal still goes through a real branch + PR; auto-merge
--     merges that PR via the GitHub API, it never pushes directly to
--     main (_assert_never_main, reused from architect_committer.py,
--     still applies).
--
-- Separate table from project_plan_actions -- that one's plan_id FK ties
-- it to project_architect's own PROJECT_PLAN.md cycles specifically;
-- this covers proposals from any agent role, so it needs its own,
-- unconstrained-by-plan_id audit trail.
CREATE TABLE IF NOT EXISTS agent_change_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name TEXT NOT NULL,
    role TEXT NOT NULL,
    file_path TEXT NOT NULL,
    title TEXT NOT NULL,
    rationale TEXT NOT NULL,
    confidence NUMERIC(5,4),
    agent_weight NUMERIC(8,5),
    effective_score NUMERIC(8,5),
    auto_merge_eligible BOOLEAN NOT NULL DEFAULT false,
    action TEXT NOT NULL CHECK (action IN ('branch_created', 'committed', 'pushed', 'pr_opened', 'merged', 'skipped', 'failed')),
    branch_name TEXT,
    commit_sha TEXT,
    pr_url TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_change_proposals_created_at_idx ON agent_change_proposals (created_at DESC);
CREATE INDEX IF NOT EXISTS agent_change_proposals_agent_name_idx ON agent_change_proposals (agent_name);

CREATE OR REPLACE FUNCTION agent_change_proposals_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'agent_change_proposals is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS agent_change_proposals_no_update ON agent_change_proposals;
CREATE TRIGGER agent_change_proposals_no_update
    BEFORE UPDATE OR DELETE ON agent_change_proposals
    FOR EACH ROW EXECUTE FUNCTION agent_change_proposals_append_only();
