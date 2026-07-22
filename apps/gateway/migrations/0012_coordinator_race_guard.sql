-- Phase 5d follow-up: a security review of _maybe_spawn_coordinator
-- (app/agent_swarm/services/swarm_coordinator.py) found its "does a
-- coordinator already exist" check was a plain SELECT-then-INSERT with
-- no supporting constraint -- two concurrent finalize_task calls for
-- the same (role, user_id) could each pass the count check before
-- either INSERT commits, spawning more than one coordinator despite
-- the intended "exactly one coordinator per role/user" invariant.
--
-- Unlike amateur (where more than one instance is a legitimate state --
-- _default_roster seeds two), "at most one coordinator per (role,
-- user_id)" is a real, intended cardinality constraint, so a partial
-- unique index is the right fix here (same "let the DB enforce the
-- invariant, ON CONFLICT DO NOTHING" pattern CLAUDE.md's own
-- upsert_entities guardrail already documents for research_entities).
-- NULLS NOT DISTINCT (PG15+): the platform-default roster uses
-- user_id IS NULL (see ensure_default_agents), and standard SQL unique
-- semantics treat every NULL as distinct from every other NULL -- a
-- plain UNIQUE index here would silently NOT prevent two
-- user_id=NULL coordinators for the same role, which is precisely the
-- case every live-verification this session actually exercised.
CREATE UNIQUE INDEX IF NOT EXISTS agent_registry_one_coordinator_per_role_user_idx
    ON agent_registry (role, user_id) NULLS NOT DISTINCT
    WHERE level = 'coordinator';
