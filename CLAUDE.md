# CLAUDE.md

Guidance for Claude Code (and human contributors) working in this repo.

## What this is

Aether Sovereign OS is a mapping + public-records research platform:
geocoding, geospatial/full-text search, and an agent-assisted research
pipeline over **public business and location records** (OpenStreetMap,
NewsAPI headlines, OpenCorporates/SEC filings). It is a due-diligence /
journalism / urban-planning research tool, not a people-search or
surveillance product. See ROADMAP.md for hard scope boundaries.

## Repo layout

```
apps/
  gateway/        Rust/Axum API gateway (geocode, search, entities, research proxy)
  web/             React 19 + Vite + TS frontend (Mapbox GL, Tailwind, shadcn/ui, Zustand)
  api/python/      FastAPI multi-agent research orchestration (OpenRouter)
data/
  pipelines/       Airflow DAGs for OSM/NewsAPI/OpenCorporates ingestion
.claude/agents/    Claude Code subagent definitions (frontend-qa, api-reviewer, ...)
docker-compose.yml Full local dev stack
```

## Scope guardrails (enforced, not aspirational)

- `research_entities.entity_type` is DB-constrained to
  `business | government_filing | location | poi | news_mention`. There is
  no `person` entity type. Do not add one without a written scope decision
  from the repo owner in ROADMAP.md.
- `entity_relationships` models corporate parent/subsidiary graphs only.
  Do not repurpose it for personal relationship mapping.
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
reviews to them over one large manual review. `SubagentStop` hooks enforce
a test gate, secret scrubbing, and an out-of-scope write block (rejects
writes that introduce a `person` entity type or hardware-tracking code
outside the phases where ROADMAP.md allows it).
