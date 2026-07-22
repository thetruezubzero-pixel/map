# CLAUDE.md

Guidance for Claude Code (and human contributors) working in this repo.

## What this is

Aether Sovereign OS is a mapping + public-records research platform:
geocoding, geospatial/full-text search, entity resolution, and an
agent-assisted research pipeline over **public business and location
records** (OpenStreetMap, NewsAPI/GDELT, OpenCorporates/SEC EDGAR, Census/
USGS). It is a due-diligence / journalism / urban-planning research tool,
not a people-search or surveillance product. See ROADMAP.md for hard
scope boundaries.

## Repo layout

```
apps/
  gateway/          Rust/Axum API gateway (geocode, search, entities, research proxy,
                      alert subscriptions CRUD, /ws/alerts, /health/streaming)
  web/               React 19 + Vite + TS frontend (Mapbox GL, Tailwind, shadcn/ui, Zustand, D3)
  api/python/        FastAPI service
    app/agents/      Multi-agent research orchestration (OpenRouter)
    app/graph/       Entity resolution (dedup/confidence scoring) + graph queries
    app/search/      Qdrant / Redis Search / Elasticsearch (hybrid search + ES|QL aggregations)
    app/routers/     research, graph, analytics, health, agent_swarm, architect endpoints
    app/streaming/   Kafka producers (SEC EDGAR, OpenCorporates, NewsAPI/GDELT, OSM)
                      + the alert dispatcher (Flink output -> per-user alerts)
    app/agent_swarm/ Weighted multi-agent swarm: credit assignment, consensus
                      voting, prompt-level distillation, heirloom persistence,
                      project introspection + the Architect's commit/PR pipeline
    app/auth.py      JWT verification for the one python-api route that needs it
data/
  pipelines/         Airflow DAGs: OSM, NewsAPI, OpenCorporates, SEC EDGAR, Census,
                      USGS, GDELT, Data.gov, entity resolution, Elasticsearch sync
streaming/           Kafka Avro schemas, ksqlDB statements, Flink CEP job -- see streaming/README.md
.claude/agents/      Claude Code subagent definitions (frontend-qa, api-reviewer, ...)
.claude/hooks/       SubagentStop hook scripts (scope-guard, secret-scrub, test-gate)
.githooks/           Same checks as git-native pre-commit/pre-push/post-merge hooks
docker-compose.yml   Full local dev stack
```

## Scope guardrails (enforced, not aspirational)

- `research_entities.entity_type` is DB-constrained to
  `business | government_filing | location | poi | news_mention`. There is
  no `person` entity type. Do not add one without a written scope decision
  from the repo owner in ROADMAP.md.
- `entity_relationships` models corporate parent/subsidiary and
  entity-resolution (`same_as`) graphs only. Do not repurpose it for
  personal relationship mapping.
- `apps/api/python/app/graph/resolve.py`'s officer-overlap signal
  (`same_officer`) compares two *company* records and returns a float; it
  must never surface the officer's name in `match_basis` or any API
  response -- see `tests/test_entity_resolution.py`'s
  `test_score_pair_officer_overlap_never_creates_a_person_record`.
- Agent prompts in `apps/api/python/app/agents/` must not ask for or
  synthesize individual dossiers. Every retrieved record is tagged with
  `source`, `retrieved_at`, and `license`.
- `agent_audit_log` is append-only at the DB level (update/delete raises).
  Do not work around this from application code.
- Research jobs default to `requires_review = true`; do not auto-finalize
  jobs without a human review step.
- Agent-swarm heirlooms (`heirloom_manifest`, `agent_registry.user_id`)
  are per-user only -- `app/agent_swarm/services/heirloom_sync.py`'s
  `import_heirloom_to_successor` enforces this at runtime (raises if
  source/successor agents belong to different users). Do not add
  cross-user knowledge sharing without a written scope decision in
  ROADMAP.md (see its "Explicit non-goals" section).
- Do not wire `IPFSBlockchainHeirloomStore`
  (`apps/api/python/app/agent_swarm/services/heirloom_sync.py`) to real
  IPFS/blockchain infrastructure without explicit authorization -- it
  spends real money (gas fees) and needs real private-key handling. See
  ROADMAP.md Phase 7.
- The `project_architect` agent could originally only ever write
  `PROJECT_PLAN.md` (`architect_committer.py`); Phase 5c
  (`change_proposer.py`) widened this, via an explicit, written scope
  decision, to also propose changes to allowlisted documentation files
  (`*.md` / `.env.example` only -- see `_assert_file_allowlisted`). It
  must still never touch `ROADMAP.md` or `CLAUDE.md` themselves -- both
  stay human-owned, including this file and ROADMAP.md's "Explicit
  non-goals" section, and both are rejected by name in
  `_assert_file_allowlisted` regardless of confidence or category. It
  must never push directly to or merge `main` itself --
  `_assert_never_main` (in both `architect_committer.py` and
  `change_proposer.py`) and the branch-then-PR-only flow are
  load-bearing, not incidental. `change_proposer.py` *can* merge the PR
  it just opened via the GitHub API when `confidence *
  agent_registry.current_weight` clears `AGENT_AUTO_MERGE_CONFIDENCE_
  THRESHOLD` and `AGENT_AUTO_MERGE_ENABLED` is explicitly on (default
  off) -- this is still a PR merge, never a direct push, and is scoped
  to the documentation allowlist only; source code and infra changes
  (`code_change`/`infra_change` categories) are still never
  autoimplementable. Do not widen the file allowlist, or wire this
  mechanism into an unauthenticated/untrusted-input-facing agent (chat,
  or any research role that processes external public records), without
  a further written scope decision in ROADMAP.md, per the same norm as
  every other guardrail in this section -- see ROADMAP.md "Phase 5b: the
  Architect" and "Phase 5c: widening safe_to_autoimplement".
- `introspection._read_full_source_tree` (gated behind
  `AGENT_FULL_SOURCE_VISIBILITY_ENABLED`, default off -- see ROADMAP.md
  "Phase 5d") reads real file contents for the Architect's snapshot.
  Its denylist (`_is_source_readable`) is the actual security boundary,
  not the flag: any `.env*` file except `.env.example`, anything with
  secret/credential/password in its name, and `.key`/`.pem`/`.p12`/`.pfx`
  files must never be read, unconditionally, regardless of the flag or
  any caller. If you add a new secret-shaped file convention to this
  repo (a new credentials format, a new key file extension), add it to
  `_is_source_readable`'s denylist in the same commit -- don't rely on
  the flag defaulting off as the only protection, since the whole point
  of this feature is that someone will eventually turn it on.

## Architecture / trust boundaries

- **`python-api` has no authentication of its own** (no JWT check, no
  API key). It must never get a host port mapping in docker-compose --
  it's reachable only via the docker network, from `gateway` (proxies
  `/research`) and `web`'s nginx (proxies `/py-api/` for graph +
  analytics). If you add a new consumer of `python-api`, route it through
  one of those two, don't expose `python-api` directly. Note that `web`'s
  `/py-api/` proxy exposes python-api's *entire* route surface with no
  auth check of its own -- a route cannot rely on "the gateway already
  verified this" for that reason. `POST /architect/run` is the one route
  that verifies its own JWT (`app/auth.py`) instead of assuming the
  gateway did, because it can trigger a real autonomous git commit + PR;
  match that pattern for any future route with real side effects.
- **ES|QL query strings must bind caller input via `params`, never
  f-string/string-interpolate it in.** `app/search/elasticsearch_setup.py`'s
  `top_entity_types_by_source` (reachable unauthenticated per the
  trust-boundary note above) used to build
  `f'... WHERE source == "{source}" ...'` directly -- a `source` value
  like `x" | LIMIT 1 | FROM some_other_index // ` broke out of the quoted
  literal and appended arbitrary ES|QL pipeline stages, confirmed by
  construction. Fixed by binding `source` to a `?` placeholder via
  `esql_query`'s `params` argument (real parameterization, not escaping).
  Any new ES|QL helper that takes caller-controlled input must do the
  same.
- **`JWT_SECRET` must be set explicitly** in any environment reachable
  outside your own machine (`docker-compose.yml` now requires it via
  `${JWT_SECRET:?...}`). The old default (`dev-only-insecure-secret`) is
  a public string in this repo's history -- anyone who knows it can forge
  a token. The gateway logs a `WARN` if it falls back to that default.
- **A `PgListener` (or any long-lived DB session) must never borrow from
  the gateway's shared `PgPool`.** `routes/alerts_ws.rs`'s `/ws/alerts`
  used to open its `PgListener` via `PgListener::connect_with(&state.db)`,
  which pulls a real connection out of the same 10-connection pool every
  other route shares and holds it for that WebSocket's entire lifetime --
  confirmed live that ~10 concurrent `/ws/alerts` connections from one
  ordinary, legitimately-issued JWT (no elevated privilege, no rate-limit
  bypass, since the route was never behind `rate_limit.rs` either)
  starved `/health`, `/search`, and `/subscriptions` gateway-wide.
  `PgListener::connect(&state.config.database_url)` opens a dedicated
  connection outside the pool instead. Any future long-held DB session
  (another LISTEN/NOTIFY consumer, a streaming export, etc.) must do the
  same, not reuse `state.db`.
- **Geo queries must be indexed on the same expression they filter on.**
  `research_entities`'s spatial queries cast `geom::geography` (for
  accurate meter-based `ST_DWithin`/`ST_Distance`), which a plain
  `geometry`-typed GIST index does *not* serve -- confirmed via
  `EXPLAIN ANALYZE` regression (a 2km-radius query against 55k rows took
  ~3s as a sequential scan before `research_entities_geog_idx`
  (`0006_geography_index.sql`) fixed it to ~20ms). If you add a new
  geometry column or a new geography-cast query, add a matching
  expression index in the same migration.
- **New `research_entities`-writing code must go through
  `upsert_entities`**, not a raw `INSERT`. It relies on the
  `(source, entity_type, name)` unique constraint
  (`0004_entities_idempotency.sql`) for its `ON CONFLICT` to actually do
  something -- without a matching unique constraint, `ON CONFLICT DO
  NOTHING` silently has nothing to conflict against (every row's `id` is
  a fresh random UUID), and "idempotent" ingestion duplicates every
  record on every re-run. This was a real, confirmed-in-production-shape
  bug until the audit that added that constraint.

## Development

- Gateway: `cd apps/gateway && cargo check` / `cargo run` (needs `DATABASE_URL`).
- Frontend: `cd apps/web && npm install && npm run dev`.
- Python orchestration: `cd apps/api/python && pip install -r requirements.txt && uvicorn app.main:app --reload`.
- Full stack: `docker compose up`.
- No hardcoded secrets. All credentials come from environment variables
  (see each app's `.env.example`).

## Subagents

`.claude/agents/` defines scoped subagents (frontend-qa, api-reviewer,
security-checker, docs-maintainer). Prefer delegating focused, parallel
reviews to them over one large manual review.

## Hooks

Two layers, same underlying scripts in `.claude/hooks/`:

- **Claude Code `SubagentStop` hooks** (`.claude/settings.json`): run
  automatically after any subagent finishes. `scope-guard.sh` blocks
  writes that touch an explicit ROADMAP.md non-goal (a `person` entity
  type, hardware-tracking code, OPSEC evasion tooling, ...);
  `secret-scrub.sh` blocks hardcoded secrets in the diff; `test-gate.sh`
  runs build/tests for whichever subproject actually changed.
- **Git hooks** (`.githooks/`, same three checks at commit/push time, plus
  a full-suite run on `post-merge`). Not enabled by default -- opt in with:
  ```
  git config core.hooksPath .githooks
  ```
