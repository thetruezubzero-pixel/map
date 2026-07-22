-- Phase 5b (agent autonomy, scoped): the Architect -- a project_architect
-- agent role that introspects the project's own state (a "digital twin"
-- snapshot), produces a ranked development plan from it, and can
-- autonomously commit ONE self-owned file (PROJECT_PLAN.md) to a
-- dedicated branch and open a PR.
--
-- Scope guardrails (see ROADMAP.md "Phase 5b: the Architect" and
-- CLAUDE.md, carried forward from Phase 5's 0008_agent_swarm.sql):
--   - The architect never merges. It proposes via a real branch + real
--     PR, same as any other contributor to this repo -- landing in
--     `main` always goes through the same human/CI-gated PR review
--     everything else does. This is an extension of, not an exception
--     to, 0008's "No autonomous action ... never a mutation applied
--     without human review."
--   - The architect may only ever write PROJECT_PLAN.md. It never
--     touches ROADMAP.md or CLAUDE.md -- those stay human-owned,
--     including ROADMAP.md's "Explicit non-goals" section, which the
--     architect treats as read-only input, never something it can
--     contradict or edit.
--   - project_snapshots/project_plans/project_plan_actions are
--     append-only, same enforcement pattern as agent_audit_log in
--     0002_phase2.sql -- a plan or action row is a historical record,
--     never edited or deleted in place.

-- 'project_architect' joins the 3 existing roles. Extends, not
-- replaces, the CHECK added in 0008_agent_swarm.sql.
ALTER TABLE agent_registry DROP CONSTRAINT agent_registry_role_check;
ALTER TABLE agent_registry ADD CONSTRAINT agent_registry_role_check
    CHECK (role IN ('query_analyzer', 'data_retriever', 'result_synthesizer', 'project_architect'));

ALTER TABLE task_history DROP CONSTRAINT task_history_role_check;
ALTER TABLE task_history ADD CONSTRAINT task_history_role_check
    CHECK (role IN ('query_analyzer', 'data_retriever', 'result_synthesizer', 'project_architect'));

-- The project's "digital twin" -- a structured snapshot of real,
-- introspected project state (DB counts, DAG/route inventory,
-- ROADMAP.md phase status, recent git log) at a point in time. Built by
-- app/agent_swarm/introspection.py::build_project_snapshot -- every
-- field is derived from live introspection, never hallucinated by the
-- LLM (the LLM only sees this JSON as input, in project_plans below).
CREATE TABLE IF NOT EXISTS project_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot JSONB NOT NULL,
    summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS project_snapshots_created_at_idx ON project_snapshots (created_at DESC);

-- A ranked development plan produced by ProjectArchitectAgent from one
-- snapshot. `items` is a JSON array of
-- {title, rationale, category, safe_to_autoimplement}; only items with
-- safe_to_autoimplement=true and category derived from the
-- PROJECT_PLAN.md-only allowlist ever reach architect_committer.py.
CREATE TABLE IF NOT EXISTS project_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID NOT NULL REFERENCES project_snapshots(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agent_registry(id) ON DELETE SET NULL,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS project_plans_snapshot_id_idx ON project_plans (snapshot_id);
CREATE INDEX IF NOT EXISTS project_plans_created_at_idx ON project_plans (created_at DESC);

-- The actual autonomous-commit audit trail: one row per real git/GitHub
-- action the architect took. This is the ledger a human reviews to see
-- exactly what the architect has done, unsupervised, to the real repo.
CREATE TABLE IF NOT EXISTS project_plan_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES project_plans(id) ON DELETE CASCADE,
    item_index INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('branch_created', 'committed', 'pushed', 'pr_opened', 'skipped', 'failed')),
    branch_name TEXT,
    commit_sha TEXT,
    pr_url TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS project_plan_actions_plan_id_idx ON project_plan_actions (plan_id);

CREATE OR REPLACE FUNCTION project_architect_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS project_snapshots_no_update ON project_snapshots;
CREATE TRIGGER project_snapshots_no_update
    BEFORE UPDATE OR DELETE ON project_snapshots
    FOR EACH ROW EXECUTE FUNCTION project_architect_append_only();

DROP TRIGGER IF EXISTS project_plans_no_update ON project_plans;
CREATE TRIGGER project_plans_no_update
    BEFORE UPDATE OR DELETE ON project_plans
    FOR EACH ROW EXECUTE FUNCTION project_architect_append_only();

DROP TRIGGER IF EXISTS project_plan_actions_no_update ON project_plan_actions;
CREATE TRIGGER project_plan_actions_no_update
    BEFORE UPDATE OR DELETE ON project_plan_actions
    FOR EACH ROW EXECUTE FUNCTION project_architect_append_only();
