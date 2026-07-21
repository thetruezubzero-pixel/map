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

## Phase 2 — Frontend + multi-agent orchestration + hybrid search (complete)

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
  Redis Search (vector+tag+geo hybrid queries), Elasticsearch (index
  mappings prepped for Phase 3 aggregation)
- Airflow DAGs: OSM ingestion, NewsAPI aggregation, OpenCorporates sync —
  each with source attribution, license tracking, PII-scrubbing middleware
- Claude Code subagents (frontend-qa, api-reviewer, security-checker,
  docs-maintainer) with `SubagentStop` hooks: test gate, secret scrubbing,
  out-of-scope write block

## Phase 3 — Free data expansion + entity resolution (complete)

Free/public sources only — no paid-tier APIs, no PACER, no county
assessor accounts (those still need credentialing + legal review, see
below).

- New Airflow DAGs: `sec_edgar_ingestion` (SEC EDGAR via EdgarTools),
  `census_tiger_sync` (TIGERweb county boundaries), `usgs_elevation_sync`
  (elevation via EPQS), `gdelt_events_sync` (GDELT 2.0 Doc API),
  `data_gov_search_sync` (CKAN dataset search — see note below),
  `opencorporates_sync` moved to weekly to stay under the free-tier quota
- Entity resolution pipeline (`apps/api/python/app/graph/`): name
  normalization + fuzzy matching, exact-ID matching (CIK/
  OpenCorporates-ID/EIN), address proximity (PostGIS `ST_DWithin`), and an
  officer-overlap signal that compares two *company* records without ever
  storing or exposing the officer's name (see CLAUDE.md guardrail).
  Confidence ≥ 0.8 auto-writes a `same_as` edge; everything else queues in
  `entity_resolution_candidates` for human review via
  `/graph/review/queue` + `/graph/review/{id}`.
- Elasticsearch activated: geo-distance search, geohash-grid heatmap
  aggregation, and ES|QL `STATS...BY` queries
  (`apps/api/python/app/search/elasticsearch_setup.py`), synced from
  Postgres by the `elasticsearch_sync` DAG. ENRICH spatial joins against
  census-tract/zoning polygons are **not** implemented — there's no
  polygon boundary layer yet, only points.
- Frontend: base-style switcher, per-entity-type layer visibility, a
  news-density heatmap layer, a Mapbox-native 3D terrain layer, an NLCD
  land-cover overlay (MRLC public WMS), a D3 force-directed entity graph
  view, and JSON/CSV/print-to-PDF export.
- `.claude/agents/` (frontend-qa, api-reviewer, security-checker,
  docs-maintainer) + `.claude/hooks/` wired to `SubagentStop`
  (scope-guard, secret-scrub, test-gate) + mirrored `.githooks/`
  (pre-commit/pre-push/post-merge) for the git-native path — opt in with
  `git config core.hooksPath .githooks`.

Known gaps, called out rather than papered over:
- `data_gov_search_sync` is written against the documented CKAN API, but
  `catalog.data.gov`'s classic API currently 404s (the site was
  restructured); the DAG fails soft until that's fixed upstream.
- No transit (GTFS) layer — Data.gov's current inaccessibility and the
  absence of a GTFS-parsing DAG mean this wasn't built, not just toggled
  off.
- No demographics-by-tract choropleth or parcel/zoning polygon layer —
  same root cause: no polygon boundary data ingested yet.
- "Business markers sized by revenue" wasn't implemented — none of the
  free sources in this phase expose revenue data.
- Qdrant and Redis Search (`apps/api/python/app/search/qdrant_setup.py`,
  `redis_search.py`) are real, independently-tested modules but are not
  called from any live endpoint, DAG, or the frontend — "hybrid search"
  today means Elasticsearch only. Wiring one of them into `/search` (or a
  new endpoint) is unstarted work, not a bug.
- The D3 entity graph view (`EntityGraphView.tsx`) is not scalable to
  large graphs as implemented: it pushes a full React state update on
  every force-simulation tick. Benchmarked at ~25s of simulation time
  alone (before React re-renders) for 10,000 synthetic nodes. This
  doesn't matter for the current usage (a single entity's depth-2
  neighborhood, typically tens of nodes) but would need tick-throttling
  (e.g. update state every N ticks, or only after the simulation settles)
  before a "view the whole graph" feature could use it.
- The Rust gateway has no OpenAPI/Swagger generation (the Python service
  does, auto-generated by FastAPI at `/docs`). Its 5 endpoints are
  documented in prose in CLAUDE.md and this file instead.

## Phase 4 (future, needs credentials/legal review)

- County assessor, PACER ingestion (still business/property records —
  requires credentialing and a legal review of each source's ToS)
- GTFS transit feeds, census-tract/zoning polygon ingestion (unlocks
  ENRICH spatial joins and choropleth layers)
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
  graph is corporate parent/subsidiary and resolved-duplicate (`same_as`)
  only. `research_entities` has no `person` type (DB-enforced, see
  CLAUDE.md). Officer/director names from SEC/OpenCorporates stay inside
  a company record's filing metadata — never their own row, never their
  own graph node.
- **No zk-SNARKs / advanced cryptography** — no stated use case.

If a future contributor believes one of these is genuinely needed, open
an issue describing the legitimate use case, the abuse potential, and
concrete safeguards, and get explicit sign-off before writing code.
