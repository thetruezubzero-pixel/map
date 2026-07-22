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
  does, auto-generated by FastAPI at `/docs`). Its endpoints are
  documented in prose in CLAUDE.md and this file instead.

## Phase 4 (built) -- streaming intelligence + real-time change detection

Kafka (KRaft) + Schema Registry + ksqlDB + Flink, real-time change
detection over the same free public-record sources as Phase 3, plus a
per-user alert subscription/delivery path. See `streaming/README.md` for
the full component breakdown, what was live-tested vs. what's a
documented gap, and the honest sub-500ms-target-vs-measured-~42s latency
finding.

- Kafka topics + Avro schemas for property/business/permit/news/
  entity-resolved/user-alert events, plus an internal
  `aether.detected_patterns` topic (Flink's raw output before per-user
  matching).
- Producers: SEC EDGAR RSS, OpenCorporates delta polling, NewsAPI+GDELT
  with sentiment, OSM changesets. Data.gov permit polling and the
  entity-resolution producer have topics/schemas ready but no producer
  yet (Data.gov's API is still down; `resolve.py` isn't wired to Kafka).
- ksqlDB streams + two materialized "latest state" views (business
  registrations by CIK, news sentiment by source).
- Flink CEP job: filing-cluster pattern detection (`MATCH_RECOGNIZE`),
  filing-volume-spike sliding-window aggregation, and a name-substring
  registration/news correlation join.
- Alert subscriptions (entity/keyword/geofence/composite) and delivery:
  Postgres `user_subscriptions`/`user_alerts`
  (`apps/gateway/migrations/0007_alerts.sql`), a dispatcher consumer
  bridging Flink's output to real per-user rows, and a Rust
  `GET /ws/alerts` WebSocket (Postgres LISTEN/NOTIFY, not a Kafka client
  in the gateway) plus `/subscriptions` CRUD and `/health/streaming`.
  Geofence subscriptions don't match anything yet -- the CEP job doesn't
  carry coordinates on its output; documented, not silently stubbed.

## Phase 5 (built) -- weighted multi-agent swarm

Upgrades the Phase 2 3-agent pipeline (query_analyzer -> data_retriever
-> result_synthesizer) into a weighted swarm with real, citable
algorithms: the Hedge/multiplicative-weights-update algorithm for credit
assignment, UCB1 exploration bonus for under-tried agents, a
Beta-Binomial Bayesian reliability estimate per agent, and a Monte Carlo
simulation for risk-aware consensus confidence. See
`apps/api/python/app/agent_swarm/` module docstrings for the exact
citations and `/agents`, `/swarm`, `/training`, `/heirlooms` in the
frontend for the dashboard.

- `agent_registry`/`task_history`/`weight_history`/`heirloom_manifest`
  (`apps/gateway/migrations/0008_agent_swarm.sql`).
- Amateur/actuarial/coordinator agent levels; amateurs run in real
  shadow mode (zero vote weight) until graduating at 90% accuracy AND 50
  consecutive successes, both required.
- `data_retriever` deliberately stays single-agent, not swarmed --
  deterministic tool execution has no judgment call for multiple
  instances to vote on.
- New `POST /research/{job_id}/review` is what triggers credit
  assignment -- it didn't exist before Phase 5, and without it credit
  assignment has no way to ever fire.
- Knowledge distillation is real prompt-level curation (few-shot
  exemplars from a senior agent's confirmed-successful outputs), not
  gradient-based weight distillation -- our agents are OpenRouter API
  calls to hosted models with no logit/weight access, so the literal
  technique from the distillation literature isn't available here.
- Heirloom persistence: a real, working `PostgresEncryptedHeirloomStore`
  (AES-256-GCM) behind a `HeirloomStore` interface. The spec's IPFS +
  blockchain attestation layer is `IPFSBlockchainHeirloomStore`, a
  documented stub that raises `NotImplementedError` rather than faking a
  hash/tx id or spending real gas fees without explicit authorization --
  see Phase 7 below for its activation plan.
- Not done, flagged rather than silently omitted: the `/agents`,
  `/swarm`, `/training`, `/heirlooms` API routes have no auth (any
  caller can pass any `user_id`) -- fine for a same-origin dev dashboard,
  not fine to expose publicly as-is.
- The full swarm success path (multiple differently-modeled agents
  actually producing different outputs and voting) is unverified beyond
  graceful degradation -- `OPENROUTER_API_KEY` in the dev/build sandbox
  is a placeholder, the same limitation already documented for
  OpenCorporates/NewsAPI in earlier phases.

## Phase 5b (built) -- the Architect

Extends the Phase 5 swarm with a 4th agent role, `project_architect`,
that introspects the project itself rather than researching public
records. See `apps/api/python/app/agent_swarm/introspection.py`,
`app/agents/project_architect.py`, and
`app/agent_swarm/services/architect_committer.py`.

- **The "digital twin"**: `project_snapshots` -- a structured, real
  snapshot of the project's own state (DB counts, DAG/route inventory,
  ROADMAP.md's phase status and non-goals, recent git log), built by
  live introspection, never hallucinated by the LLM.
- **The plan**: `project_plans` -- `project_architect` produces a ranked
  list of next steps from one snapshot, each item citing the specific
  snapshot fact that motivates it.
- **The one bounded autonomous-commit exception**: the architect may
  write exactly one file, `PROJECT_PLAN.md`, to a dedicated
  `agent/architect/...` branch, and open a real PR. It never merges.
  This is deliberately consistent with, not an exception to, Phase 5's
  own stated boundary (`0008_agent_swarm.sql`: "No autonomous action ...
  never a mutation applied without human review") -- landing in `main`
  always goes through the same human/CI-gated PR review every other
  change in this repo does, including the architect's own.
  `architect_committer.py`'s `_assert_never_main` makes a direct push to
  `main` structurally impossible, called before every push and again
  immediately before the PR is opened. Every action (branch created,
  committed, pushed, PR opened, or skipped/failed and why) is written to
  `project_plan_actions`, append-only at the DB level like
  `agent_audit_log`.
- **Growth within the existing swarm, not a parallel system**: registered
  in `agent_registry` like any other role; can graduate `amateur` ->
  `actuarial` under the same 90%-accuracy/50-consecutive-successes rule.
  Every action is written to `agent_audit_log` via the same `Agent.audit()`
  base method the other 3 agents use.
- Runs on a daily Airflow DAG (`project_architect_cycle_dag.py`) rather
  than a bespoke scheduler -- python-api has none of its own.
  `POST /architect/run` is the one route in this feature gated behind
  JWT (`app/auth.py`): it's reachable unauthenticated via web's nginx
  `/py-api/` proxy otherwise, same as every python-api route (see
  CLAUDE.md), and this one can trigger a real commit + PR, so it
  verifies the token itself rather than trusting the gateway already did.
- `GITHUB_TOKEN` (a fine-grained PAT scoped to *only* this repo, with
  *only* Contents and Pull-requests permissions -- never anything that
  could merge) and `ARCHITECT_AUTO_COMMIT_ENABLED` (default `true`, a
  kill switch independent of the token) gate the commit/PR step
  specifically. Snapshotting and planning work with no token at all --
  visible on `/architect` either way.
- Not done, flagged rather than silently omitted: `safe_to_autoimplement`
  is currently restricted, by construction, to `PROJECT_PLAN.md` only --
  the architecture doesn't prevent widening that allowlist once there's
  a track record of reviewed, merged PRs (the same shadow-mode ->
  graduation trust-building pattern Phase 5 already uses for amateur
  agents), but that widening is a future, separate decision, not
  something this phase does on its own.

## Phase 6 (partially built; remainder needs credentials/legal review)

- **Built**: GTFS transit feeds (`gtfs_transit_sync` -- static stop data,
  no schema change, lands in `research_entities` like any other point
  source) and real census-tract/zoning polygon ingestion
  (`census_tract_boundary_sync`, `zoning_districts_sync`), storing actual
  polygon geometry -- not just centroids -- in a new
  `research_entity_boundaries` table
  (`apps/gateway/migrations/0010_entity_boundaries.sql`) with a GIST index
  for `ST_Intersects` point-in-polygon joins, exposed via `GET
  /boundaries`. This unlocks the spatial-join/choropleth groundwork this
  item originally called for; a frontend choropleth layer consuming it is
  still a separate, unbuilt task. Only one seed source is wired per
  boundary type so far (NYC DCP zoning, Census tracts for NYC/SF
  counties) -- extending coverage means adding more seed
  counties/bboxes/agencies, following the existing DAG pattern, not new
  architecture.
- County assessor, PACER ingestion (still business/property records —
  requires credentialing and a legal review of each source's ToS)
- Flink JDBC connector once a Flink-2.x-compatible release exists (would
  replace the Postgres-side alert_dispatcher.py matching step with a live
  join inside Flink itself)

## Phase 7 (future, needs real infrastructure + explicit authorization)

- Activate `IPFSBlockchainHeirloomStore`
  (`apps/api/python/app/agent_swarm/services/heirloom_sync.py`): real
  IPFS pinning service credentials, a real wallet with funded gas on
  whichever chain (Polygon was the sandbox's suggestion, cheap L2 gas),
  and explicit sign-off before any real transaction is sent, since this
  spends real money and needs real private-key handling. Until then,
  `PostgresEncryptedHeirloomStore` is the only backend and heirlooms
  don't leave this platform's own database.

## Explicit non-goals (require a written scope decision to ever revisit)

These are not "later phases" in the normal sense — each one changes the
product from public-records research into individual surveillance, and
must not be built without an explicit, separate decision by the repo
owner, documented here with rationale and safeguards:

- **No hardware tracking layer.** No Bluetooth/cellular/WiFi scanning or
  device-presence tracking, consented or otherwise. This product does not
  track people's physical devices.
- **No blockchain identity / DID system** for user or subject identity.
  (Phase 7's `IPFSBlockchainHeirloomStore` is scoped narrowly to agent
  *weight snapshot* content-addressing/attestation, not identity -- it
  still isn't built/wired yet either way, see Phase 7 above.)
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
