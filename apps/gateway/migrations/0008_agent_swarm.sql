-- Phase 5: weighted multi-agent swarm -- agent registry, task-level
-- consensus/credit-assignment history, weight history, and per-user
-- heirloom (cross-device knowledge persistence) manifest.
--
-- Scope guardrails (see CLAUDE.md / ROADMAP.md, carried forward from
-- earlier phases):
--   - Agents research *business/public-record* queries only; nothing
--     here introduces a person entity type or individual profiling.
--   - Heirlooms are strictly per-user (user_id is NOT NULL, never
--     shared across users) -- see agent_registry.user_id and
--     heirloom_manifest.user_id.
--   - No autonomous action: task_history.consensus_output is advisory
--     input to the existing research_jobs review flow, never a
--     mutation applied without human review (requires_review is
--     already true by default on research_jobs, unchanged here).

CREATE TABLE IF NOT EXISTS agent_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    -- Which of the existing 3 agent roles (app/agents/) this instance
    -- fills. Not an open string -- must match a real orchestrator role.
    role TEXT NOT NULL CHECK (role IN ('query_analyzer', 'data_retriever', 'result_synthesizer')),
    level TEXT NOT NULL CHECK (level IN ('amateur', 'actuarial', 'coordinator')),
    model TEXT NOT NULL,
    current_weight NUMERIC(8,5) NOT NULL DEFAULT 1.0 CHECK (current_weight >= 0),
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    total_tasks INTEGER NOT NULL DEFAULT 0,
    total_successes INTEGER NOT NULL DEFAULT 0,
    -- Graduation criteria (spec: 90% accuracy + 50 consecutive
    -- successes) is evaluated in application code against the counters
    -- above; `graduated` caches the last evaluation so shadow-mode
    -- filtering doesn't need to recompute it on every read.
    graduated BOOLEAN NOT NULL DEFAULT false,
    -- Recursive seniority: heirloom lineage (senior agent -> successor).
    parent_agent_id UUID REFERENCES agent_registry(id) ON DELETE SET NULL,
    -- Amateur -> actuarial mentorship pairing (one mentor per amateur).
    mentor_agent_id UUID REFERENCES agent_registry(id) ON DELETE SET NULL,
    -- Heirlooms/weights are per-user; NULL user_id means a shared
    -- platform-default agent (not eligible for heirloom export).
    user_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_registry_role_level_idx ON agent_registry (role, level);
CREATE INDEX IF NOT EXISTS agent_registry_user_id_idx ON agent_registry (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS agent_registry_parent_agent_id_idx ON agent_registry (parent_agent_id) WHERE parent_agent_id IS NOT NULL;

-- One row per role-execution within a research job: which agent
-- instances voted, what each proposed, what the weighted consensus
-- picked, and (once a human reviews the job) what the ground-truth
-- outcome was -- which is what credit_assigner.py rewards/penalizes
-- against. Nothing here is applied automatically; research_jobs.result
-- remains the actual output surfaced to the API, same as before Phase 5.
CREATE TABLE IF NOT EXISTS task_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES research_jobs(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK (role IN ('query_analyzer', 'data_retriever', 'result_synthesizer')),
    agents_involved UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
    -- Per-agent votes: [{"agent_id": "...", "confidence": 0.0-1.0, "output": {...}, "reasoning": "..."}]
    votes JSONB NOT NULL DEFAULT '[]'::jsonb,
    consensus_output JSONB NOT NULL DEFAULT '{}'::jsonb,
    winning_agent_id UUID REFERENCES agent_registry(id) ON DELETE SET NULL,
    -- Filled in once a human reviews the job outcome (or the job fails
    -- outright) -- reward_applied stays false until credit_assigner.py
    -- has actually processed it, so it never double-applies a reward.
    ground_truth JSONB,
    reward_applied BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS task_history_job_id_idx ON task_history (job_id);
CREATE INDEX IF NOT EXISTS task_history_pending_reward_idx ON task_history (reward_applied) WHERE NOT reward_applied;

CREATE TABLE IF NOT EXISTS weight_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agent_registry(id) ON DELETE CASCADE,
    weight NUMERIC(8,5) NOT NULL,
    delta NUMERIC(8,5) NOT NULL,
    -- 'task:<task_history.id>' for a credit-assignment update, 'decay'
    -- for the periodic time-decay pass, 'exploration_bonus' for a new
    -- agent's UCB1 bonus. Not a free-text field application code
    -- should regex-match against -- see credit_assigner.py for the
    -- exact reason strings it writes.
    reason TEXT NOT NULL,
    task_id UUID REFERENCES task_history(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS weight_history_agent_id_idx ON weight_history (agent_id, created_at DESC);

-- Cross-device heirloom persistence. backend='postgres_encrypted' is the
-- only backend actually wired up in this phase -- see
-- app/agent_swarm/services/heirloom_sync.py's HeirloomStore interface
-- and ROADMAP.md for why 'ipfs_blockchain' is a documented future
-- adapter, not live infrastructure, in this phase.
CREATE TABLE IF NOT EXISTS heirloom_manifest (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agent_registry(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    backend TEXT NOT NULL DEFAULT 'postgres_encrypted' CHECK (backend IN ('postgres_encrypted', 'ipfs_blockchain')),
    -- sha256 of the plaintext weight-snapshot JSON -- content-addressed
    -- identity independent of which backend stores the bytes, so a
    -- future ipfs_blockchain row can be verified against the same hash
    -- an existing postgres_encrypted row already committed to.
    content_hash TEXT NOT NULL,
    encrypted_payload BYTEA,
    ipfs_hash TEXT,
    blockchain_tx TEXT,
    verified BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (backend <> 'postgres_encrypted' OR encrypted_payload IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS heirloom_manifest_agent_id_idx ON heirloom_manifest (agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS heirloom_manifest_user_device_idx ON heirloom_manifest (user_id, device_id);
