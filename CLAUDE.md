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
  gateway/          Rust/Axum API gateway (geocode, search, entities, research proxy)
  web/               React 19 + Vite + TS frontend (Mapbox GL, Tailwind, shadcn/ui, Zustand, D3)
  api/python/        FastAPI service
    app/agents/      Multi-agent research orchestration (OpenRouter)
    app/graph/       Entity resolution (dedup/confidence scoring) + graph queries
    app/search/      Qdrant / Redis Search / Elasticsearch (hybrid search + ES|QL aggregations)
    app/routers/     research, graph, analytics, health endpoints
data/
  pipelines/         Airflow DAGs: OSM, NewsAPI, OpenCorporates, SEC EDGAR, Census,
                      USGS, GDELT, Data.gov, entity resolution, Elasticsearch sync
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
