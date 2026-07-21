# ROADMAP

## Product intent

A research platform for **public business, property, and location
records** — built for due diligence, journalism, and urban planning.
Explicitly not a people-search, dossier-building, or device-tracking
product. See "Non-goals" below; these are hard boundaries, not
aspirations, and several are enforced at the schema/hook level (see
CLAUDE.md).

## Phase 1 — Foundation (complete)

- Rust/Axum gateway: `/health`, `/geocode` (Nominatim proxy)
- Rate limiting (burst-then-steady), User-Agent hygiene, strict CORS
- PostgreSQL + PostGIS schema: `locations`, `research_entities`
- Docker Compose local dev stack
- CLAUDE.md + ROADMAP.md scope boundaries

## Phase 2 — Frontend + multi-agent orchestration + hybrid search (this phase)

- React 19 frontend (Mapbox GL, Tailwind, shadcn/ui, Zustand): search UI,
  faceted filters, map interactions, timeline scrubber
- Gateway expansion: `/search` (PostGIS + full-text), `/entities/{id}`,
  `/research` (async job kickoff, proxied to the Python orchestrator),
  per-user JWT rate limiting alongside per-IP
- Python/FastAPI multi-agent orchestration (OpenRouter model routing):
  query analyzer, data retriever (OSM/NewsAPI/OpenCorporates, public
  records only), result synthesizer (business entity graphs, timelines).
  Human-in-the-loop review queue. Immutable audit log.
- Hybrid search foundation: Qdrant (vector + geo payload filtering),
  Redis Search (FT.HYBRID), Elasticsearch (index mappings prepped for
  Phase 3 aggregation)
- Airflow DAGs: OSM ingestion, NewsAPI aggregation, OpenCorporates sync —
  each with source attribution, license tracking, PII-scrubbing middleware
- Claude Code subagents (frontend-qa, api-reviewer, security-checker,
  docs-maintainer) with `SubagentStop` hooks: test gate, secret scrubbing,
  out-of-scope write block

## Phase 3 (future, needs credentials/legal review)

- County assessor, SEC EDGAR, PACER ingestion (public filings, still
  business/property records — requires credentialing and a legal review
  of each source's ToS before ingestion starts)
- Elasticsearch aggregation layer activated

## Phase 4+ (future, unscheduled)

- Streaming pipeline (Kafka/Flink)

## Explicit non-goals (require a written scope decision to ever revisit)

These are not "later phases" in the normal sense — each one changes the
product from public-records research into individual surveillance, and
must not be built without an explicit, separate decision by the repo
owner, documented here with rationale and safeguards:

- **No hardware tracking layer.** No Bluetooth/cellular/WiFi scanning or
  device-presence tracking, consented or otherwise. This product does not
  track people's physical devices.
- **No blockchain identity / DID system** for user or subject identity.
- **No OPSEC evasion tooling** — no decoy traffic generation, fingerprint
  randomization, or anti-attribution features. This is a research tool
  that operates in the open, not a covert collection tool.
- **No individual dossiers or personal relationship mapping.** The entity
  graph is corporate parent/subsidiary only. `research_entities` has no
  `person` type (DB-enforced, see CLAUDE.md).
- **No zk-SNARKs / advanced cryptography** — no stated use case.

If a future contributor believes one of these is genuinely needed, open
an issue describing the legitimate use case, the abuse potential, and
concrete safeguards, and get explicit sign-off before writing code.
