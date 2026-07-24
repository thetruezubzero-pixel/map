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
  census-tract/zoning polygons are **not** implemented — Phase 6 added
  the polygon boundary layer (`research_entity_boundaries`) this would
  join against, but wiring an actual ES ENRICH policy is still a
  separate, unbuilt task.
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
- ~~No transit (GTFS) layer~~ — built in Phase 6 (`gtfs_transit_sync`).
- ~~No demographics-by-tract choropleth or parcel/zoning polygon layer~~
  — the polygon boundary data and the frontend choropleth layer were
  both built in Phase 6; an actual ES ENRICH policy joining against it
  is the one piece still not wired (see Phase 3's Elasticsearch bullet
  above).
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
  consecutive successes, both required. `coordinator` existed in the
  schema/CHECK constraint from this phase on, but nothing actually
  promoted an agent to it until Phase 5c's `_maybe_spawn_coordinator`
  (see below) -- a stricter, separate bar (97% accuracy, 150 consecutive
  successes, 200 minimum total tasks) than amateur->actuarial
  graduation, and `consensus_vote._break_tie` now prefers a coordinator
  vote over an actuarial one the same way actuarial already outranked
  amateur.
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
- `safe_to_autoimplement` was restricted, by construction, to
  `PROJECT_PLAN.md` only as of this phase -- see Phase 5c below for the
  explicit, separate decision that widened it to allowlisted
  documentation files, with its own safeguards.

## Phase 5c (built) -- widening safe_to_autoimplement

Phase 5b's own text flagged this as a deliberate future decision, not
something that phase did on its own: "the architecture doesn't prevent
widening that allowlist once there's a track record of reviewed, merged
PRs ... but that widening is a future, separate decision." This is that
decision, made explicitly by the repo owner, with the following scope
and safeguards -- see `apps/api/python/app/agent_swarm/services/
change_proposer.py`.

**What changed**: `project_architect` can now propose changes to
allowlisted documentation files (not just `PROJECT_PLAN.md`), and can
have those changes merged automatically without a human clicking
"merge" -- when, and only when, all of the following hold:

1. **A hard, code-enforced file allowlist** -- `change_proposer.
   _assert_file_allowlisted` accepts only markdown docs (`*.md`) and
   `.env.example` templates. `CLAUDE.md` and `ROADMAP.md` are explicitly
   rejected by name, staying human-owned exactly as Phase 5b already
   established. Source code, CI workflows, migrations, Dockerfiles,
   `docker-compose.yml`, and anything not matching those two suffixes
   are never reachable through this path -- this check runs before any
   git operation, is not derived from model output, and cannot be
   overridden by a high confidence score. Two gaps caught and fixed by
   this phase's own security review before it shipped: the allowlist
   comparison was originally case-sensitive, so `claude.md`/`Claude.MD`
   slipped past the `CLAUDE.md`/`ROADMAP.md` block (a real bypass on any
   case-insensitive filesystem, where it would resolve to the *same
   file*) -- fixed by lowercasing both sides of the comparison, same
   pattern `architect_committer._assert_never_main` already used for
   branch names. Separately, the path-traversal check was string-only
   (rejecting literal `..` segments); `_assert_resolves_within_project_root`
   now also resolves symlinks in any existing parent directory and
   confirms the real path still lands inside the project root.
2. **A real, non-model-asserted gate**: `effective_score = confidence *
   agent_weight`. `confidence` is the proposing agent's own self-reported
   confidence in that specific item (0.0-1.0, part of `ProjectPlanItem`).
   `agent_weight` is that agent's *tracked* `agent_registry.current_weight`
   -- the same weight `credit_assigner.py` already earns/decays from real
   task outcomes for every other role, not a number an agent can just
   assert about itself. Only when this product clears
   `AGENT_AUTO_MERGE_CONFIDENCE_THRESHOLD` (env `AGENT_AUTO_MERGE_
   CONFIDENCE_THRESHOLD`, default 0.9) does a proposal become
   merge-eligible -- *and* only once the agent has completed at least
   `AGENT_AUTO_MERGE_MIN_TRACK_RECORD` (default 10) prior cycles.
   Caught during this phase's own security review before it shipped: a
   brand-new agent's `current_weight` starts at `1.0` -- the neutral
   prior every agent seeds at, not zero -- so `effective_score` alone
   could clear the threshold on an agent's very first cycle with no
   actual track record behind it, contradicting "not a number an agent
   can just assert." The minimum-cycles requirement closes that gap;
   without it, the weight term wasn't providing the protection its own
   description claimed.
3. **A default-off kill switch**: `AGENT_AUTO_MERGE_ENABLED` (default
   `false`) gates the actual auto-merge call independently of the score
   -- same shape as `ARCHITECT_AUTO_COMMIT_ENABLED`. The mechanism exists
   in code either way; auto-merge is inert until the repo owner
   deliberately turns it on.
4. **Still a real branch + real PR, always**: auto-merge means "the PR
   that was just opened gets merged via the GitHub API," never a direct
   push to `main`. `_assert_never_main` (reused from
   `architect_committer.py`) still applies unconditionally. Every step
   (branch created, committed, pushed, PR opened, merged, skipped, or
   failed, and why) is written to `agent_change_proposals`
   (`0011_agent_change_proposals.sql`), append-only at the DB level like
   `agent_audit_log`/`project_plan_actions` -- the ledger a human reviews
   to see exactly what was auto-merged and on what basis.
5. **`code_change` and `infra_change` categories are still never
   autoimplementable**, by the same model-output filter
   `project_architect.py`'s `_parse` already applied to everything but
   `project_plan_doc` -- this phase only widens the allowlist to
   `documentation`, not to source code or infrastructure.

**Why this doesn't reopen the injection risk the repo owner and I
discussed before building this**: the risk was specifically an
unauthenticated, user-facing surface (chat, or any research agent
processing untrusted external data like news articles or business
records) being able to trigger a live code mutation from attacker-
controlled text. This phase deliberately does not wire that -- the
generalized `change_proposer.propose_change` function is available to
any agent module in principle, but it is only actually called from
`project_architect`'s own scheduled cycle
(`project_architect_cycle_dag.py`), which reasons over a curated,
introspected project snapshot, not raw untrusted external content or
live chat input. Wiring `chat_agent` or the research swarm roles
(`query_analyzer`/`data_retriever`/`result_synthesizer`) into this same
mechanism -- given they process user chat messages and external public
records, both attacker-reachable text -- is a separate, larger decision,
not taken here, and would need its own explicit scope review given the
different risk shape.

## Phase 5d (built) -- coordinator promotion + full source visibility

Two more explicit scope decisions, made by the repo owner in the same
conversation as Phase 5c: agents should be able to produce a genuinely
more senior successor than themselves, and the Architect should be able
to see real source file contents, not just a curated summary.

**Coordinator promotion** (`swarm_coordinator._maybe_spawn_coordinator`,
`agent_weight.meets_coordinator_promotion_criteria`): `coordinator` has
existed in `agent_registry`'s schema since Phase 5, but nothing ever
promoted an agent to it before this. An actuarial agent that clears a
real, stricter-than-graduation bar (97% accuracy, 150 consecutive
successes, 200 minimum total tasks -- all three required, same "both
conditions, not either" shape as amateur->actuarial graduation) spawns
exactly one coordinator successor for its (role, user_id), using
`OPENROUTER_COORDINATOR_MODEL` when an operator has actually configured
a stronger model (falling back to `openrouter_default_model` otherwise
-- "better than itself" is only claimed when it's real).
`consensus_vote._break_tie` now prefers a coordinator vote over an
actuarial one, the same way actuarial already outranked amateur. Pure
registry bookkeeping, same trust level as `_maybe_spawn_amateur` --
grants no git/PR/filesystem capability, so none of Phase 5c's guardrails
apply to it. A security review of this phase's own diff, before it was
committed, found the "does a coordinator already exist" check was a
plain count-then-insert with no supporting constraint -- two concurrent
`finalize_task` calls for the same (role, user_id) could each pass the
check before either INSERT committed. Fixed with a real DB-level
guarantee: `agent_registry_one_coordinator_per_role_user_idx`
(`0012_coordinator_race_guard.sql`), a `NULLS NOT DISTINCT` partial
unique index (the platform-default roster uses `user_id IS NULL`, and
plain `UNIQUE` treats every `NULL` as distinct from every other `NULL`
-- confirmed live that a naive `UNIQUE` index would NOT have closed this
for the most common case), paired with `ON CONFLICT ... DO NOTHING` at
the insert site so the losing side of a race no-ops cleanly instead of
erroring.

**Full source visibility** (`introspection._read_full_source_tree`,
gated by `AGENT_FULL_SOURCE_VISIBILITY_ENABLED`, default off): the
Architect's snapshot previously included only a curated summary (DB
counts, DAG/route inventories, ROADMAP.md excerpts, git log subjects),
specifically to bound cost and avoid ever handing a file to OpenRouter
that might contain a secret. This phase adds the option to include real
file contents, line-by-line, for every file in the repo except ones
excluded by a hard denylist (not an allowlist, since "every file" is the
point): any `.env*` file except `.env.example`, anything with
secret/credential/password in its name, `.key`/`.pem`/`.p12`/`.pfx`
files, and anything under `.git`/`node_modules`/`target`/`dist`/build or
cache directories -- checked before any file is read, unconditionally,
regardless of this flag. Capped at `AGENT_FULL_SOURCE_VISIBILITY_MAX_CHARS`
(default 2MB) total, not per file -- confirmed live this repo's own
readable source is ~694KB across 180 files as of this phase, well within
that cap; if a future repo's source ever exceeds it, `truncated: true`
is set on the snapshot (and surfaced in `summarize_snapshot`'s one-line
summary) rather than silently dropping files with no signal. This is a
real cost (every architect cycle would embed the whole repo in its
OpenRouter prompt) and third-party-exposure tradeoff versus the curated
summary, which is exactly why it defaults off -- turning it on is a
separate, deliberate choice for whoever runs this deployment, same
pattern as every other capability flag in this codebase
(`ARCHITECT_AUTO_COMMIT_ENABLED`, `AGENT_AUTO_MERGE_ENABLED`). A security
review of this feature before it was committed found and fixed two real
gaps in `_is_source_readable`'s denylist: the secret-shaped-token check
(`secret`/`credential`/`password`) only inspected the leaf filename, so
an innocuously-named file inside a secret-shaped directory (e.g.
`secrets/db.yml`) would have slipped through -- now every path
component is checked, directories included. Separately,
`_read_full_source_tree` now resolves each candidate path and confirms
it still lands inside `project_root` before reading it, since
`is_file()`/`read_text()` both follow symlinks but the denylist itself
only inspects a symlink's own name -- a symlinked path pointing outside
the checked-out tree would otherwise have its target's content read and
embedded in the snapshot. No such symlink or secrets-shaped directory
exists in this repo today (confirmed by enumerating every file the
denylist currently lets through), but both are real gap classes, not
hypothetical ones, closed before this flag could ever be turned on
against a real deployment.

**User-facing communication stays single-voice and English-only.**
`chat_agent`, `result_synthesizer`, and `project_architect`'s system
prompts each now explicitly require their free-text output (chat
replies, report summaries, plan rationale/notes) to be in English
regardless of the input language or any internal representation used
between agents. Each of these surfaces already produces exactly one
synthesized response per turn/job/cycle -- the swarm's individual votes
are visible on `/swarm`/`/agents` as a transparency/debugging view, not
as multiple agents "talking to" the user simultaneously; that
distinction is deliberate and unchanged by this phase.

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

## Phase 8 (partially built) — electrical/RF infrastructure public records

Public institutional records about electromagnetic infrastructure -- not
device tracking, not signal interception. Each source below is a
licensed/registered public database, ingested the same way SEC EDGAR/
OpenCorporates/Census already are: source-tagged, licensed, timestamped,
landing in `research_entities` as `business`/`location`/`government_filing`
rows. This does not touch the hardware-tracking non-goal below -- that
non-goal is about scanning for/locating people's physical devices
(Bluetooth/cellular/WiFi presence tracking); FCC license records and
utility infrastructure locations are public institutional data, the same
category as the zoning/census-tract records Phase 6 already ingests.

- **Built**: `fcc_spectrum_licensing_sync` (`data/pipelines/dags/
  fcc_spectrum_licensing_dag.py`) -- real FCC ULS license records
  (licensee name, call sign, transmitter lat/lon, frequency band),
  landing as `entity_type='government_filing'`. No signal detection, no
  hardware access -- a database query against a public government
  dataset, identical in shape to `sec_edgar_ingestion_dag.py`. Confirmed
  live against opendata.fcc.gov's Socrata mirror of ULS data (no API key,
  no auth) -- the FCC's own www.fcc.gov developer API (License View API)
  sits behind Akamai bot-protection that blocked every request from this
  sandbox regardless of User-Agent, so opendata.fcc.gov's dataset mirror
  is used instead. Only one ULS dataset is wired so far ("ULS 3650 MHz
  Band Locations", 7,829 records) -- extending coverage means adding
  another (label, source_slug, resource_id) tuple to the DAG's seed list,
  following the existing pattern, not new architecture.
- **Utility/grid infrastructure GIS layers**: public transmission-line
  and substation location data from utility open-data portals, following
  the same boundary-polygon pattern as `zoning_districts_dag.py`/
  `census_tract_boundary_dag.py`.
- **Semiconductor filing enrichment**: tag existing SEC EDGAR ingestion
  for chip/NPU/CPU/GPU-related filings so they're findable as a filtered
  subset -- no new data source, just better tagging of what's already
  ingested.
- **Built**: cross-source blending for the FCC piece --
  `fcc_spectrum_licensing_dag.py`'s `link_to_business_entities` task
  links a business's FCC license to its existing `research_entities` row
  by exact normalized-name match (`app.graph.normalize.normalize_name`,
  the same function `entity_resolution_dag.py` uses for business-to-
  business dedup), written as a new, distinct
  `entity_relationships.relation_type` ('holds_fcc_license') rather than
  `same_as` -- an FCC filing and a business record are related, not the
  same real-world entity, so overloading same_as would have been
  semantically wrong. Confirmed live end-to-end against a real Postgres
  instance: a seeded business + matching FCC filing produced a real
  `entity_relationships` row, and re-running the insert was correctly a
  no-op (idempotent). Blending for utility/substation records (once that
  data source lands) follows the identical pattern -- a new task, same
  normalize_name-based matching, a new relation_type.

## Phase 10 (groundwork built) — conversational map control

The connective spine for "you talk, the agent operates the map." Instead
of the user driving eight separate dashboards, they type plain English on
the map and the agent performs the search/filter/layer/viewport changes
itself.

- **Built**: a typed `MapAction` protocol (`app/agents/map_intent.py`
  `MapAction`, mirrored by `apps/web/src/lib/api.ts`'s `MapAction`) and a
  deterministic `parse_map_intent()` that turns plain English into those
  actions **with no API key required** -- regex/keyword matching over a
  declarative synonym table, so the map responds to commands even with
  `OPENROUTER_API_KEY` unset. When a key is present, `chat_agent` still
  writes the conversational reply on top; the actions are additive.
- **Built**: `POST /chat` now returns `actions: list[MapAction]` alongside
  `reply`/`grounding` (no new persistence, still stateless). The frontend
  executes them through a single dispatch point, `apps/web/src/lib/
  mapActions.ts`'s `applyMapActions` (geocodes named places via the
  gateway's Nominatim proxy, runs the real `/search`, updates
  `useMapStore`), driven from `AgentCommandBar` overlaid on the map.
- **Scope-safe by construction**: the parser only ever emits the
  DB-constrained entity allowlist (business/government_filing/location/
  poi/news_mention) -- there is no person type and no device/tracking
  action type, so a "track this phone" style request produces no map
  action (the model reply, or the deterministic fallback, handles the
  refusal). Reuses the already-rate-limited `/py-api/chat` nginx location,
  so it adds no new unthrottled external-cost path. Tests:
  `tests/test_map_intent.py` (15) and `apps/web/src/lib/mapActions.test.ts`
  (9).
- **Extensible on purpose** (per the repo owner's "this will grow" note):
  a new agent capability is one `MapActionType` value + one matcher in the
  parser + one case in `applyMapActions`. This is the seam every later
  "idea" (richer entity-graph connectivity, clustering, new record layers)
  plugs into so it becomes something the agent *does*, not another panel.
- **Built (combining the conversational layer with the research swarm)**:
  - *Grounding on the map (Combine A)*: `chat_agent._search_grounding` now
    selects `ST_X/ST_Y(geom)` and `ChatGroundingRecord` carries `lon/lat`,
    so the entities the chat agent cites are plotted on the map
    (`plotLocatedRecords`) when a turn didn't otherwise populate it. The
    conversational agent and the map now draw from the same
    `research_entities` rows.
  - *Research hand-off (Combine B)*: a new `research` `MapAction` + parser
    trigger ("research/investigate/dig into/deep dive on X") launches the
    full `POST /research` swarm from the command bar; `AgentCommandBar`
    polls the job and plots its located records + surfaces the summary when
    it lands. Scope is still enforced by the swarm's `query_analyzer`
    (empty plan for out-of-scope), and human review is unchanged -- a
    finished job sits in `awaiting_review`; the map only *displays* it,
    never auto-finalizes. Reuses the already-rate-limited create path.
  - The `chat_agent` system prompt now knows it's wired to the map (speaks
    as "I've put these on the map / I'm running a full research job on X").
- **Not built (deliberate next steps)**: *persisting live research results
  into `research_entities`* via `upsert_entities` (Combine C) so a job's
  findings become permanently searchable like DAG-ingested data -- this
  touches the DB write path and the `(source, entity_type, name)`
  idempotency guardrail, so it's a separate, deliberate change; real
  inter-agent deliberation for disagreement cases (see the
  async-cooking-giraffe plan); and marker clustering for large result sets
  (`EntityGraphView` tick-throttling caveat in Phase 3 applies to any
  "whole graph" view).

## Phase 9 (built) — Native iOS App

Production-ready iOS application for iPhone/iPad, enabling full access to
Aether Sovereign OS on mobile devices. Responsive React Native / SwiftUI
wrapper around the existing REST APIs, with native-code patterns for
authentication, location services, real-time WebSocket subscriptions, and
offline caching.

- **Built**: Complete native Swift/SwiftUI iOS app architecture with
  Combine reactive programming, Alamofire HTTP client, Mapbox GL integration,
  and Realm database for offline entity caching.
- **Built**: Authentication system (JWT stored in Keychain, auto-refresh on
  expiration, logout cascade).
- **Built**: Network manager with certificate pinning, automatic retry logic,
  and WebSocket support for real-time alerts.
- **Built**: Location services integration (GPS, permission handling, graceful
  degradation if denied).
- **Built**: App Store distribution infrastructure (Info.plist with all
  required capabilities, Entitlements.plist for iOS signing, Build.xcconfig
  for Xcode build configuration).
- **Built**: Full App Store metadata and privacy compliance
  (app-store-metadata.yaml, PRIVACY.md with full transparency on data
  collection/sharing/retention, links to policy).
- **Built**: CocoaPods dependency management (Podfile with production
  dependencies: networking, geospatial, reactive programming, testing,
  analytics, security).
- **Built**: Xcode project scaffolding (App.swift entry point, tab-based
  navigation, multiple view stubs for map/search/research/agents/heirlooms/
  chat/settings, login/logout flow).
- **Built**: Asset catalog infrastructure (app icons in all required sizes,
  launch screen, color sets for dark/light themes).
- **Built**: Export profiles for multiple distribution channels (App Store,
  TestFlight beta, enterprise MDM).
- **Mobile-optimized frontend** (from parallel concurrent work): responsive
  Tailwind design, mobile-first with sm: breakpoint overrides, 375-430px
  viewport tested, text abbreviations and layout stacking for small screens,
  line-clamping and ellipsis for overflow.
- **Not built**: Actual app icons (currently placeholders in asset catalog).
  Icon generation needs vector logo + 18 different sizes. See DEPLOYMENT.md
  / CODESPACES.md for App Store submission checklist.
- **Not built**: Actual screenshots for App Store listing (framework ready in
  app-store-metadata.yaml, need 5-8 real screenshots per device class).
- **Not built**: App code signing / provisioning profiles (infrastructure
  documented, needs real Apple Developer account / team ID).
- **Not built**: Real end-to-end iOS build and simulator test (Xcode /
  Swift SDK already specified, but requires macOS + Xcode toolchain).

## Phase 11 (built) — agent-driven repository maintenance & security (bounded)

Explicit scope decision by the repo owner: the agents should help keep the
repository itself secure, clean, and maintained — but through the same
bounded, human-reviewed channel every other agent capability uses, never
via unrestricted or autonomous control. This phase widens what the
Architect is *aware of*, not what it may write on its own.

Motivation: this repo's own CI was silently red for a while because a
GitHub Action was pinned to a version GitHub later hard-deprecated
(`actions/upload-artifact@v3`) — a maintenance-rot class no agent was
watching for.

- **Built (read-only)**: `introspection._scan_repo_health` adds a
  `repo_health` section to the Architect's digital-twin snapshot:
  `deprecated_actions` (GitHub Actions pinned below GitHub's current
  baseline, per `_MIN_ACTION_MAJOR`) and `committed_secret_files`
  (secret-bearing files that appear tracked in git, via a narrow,
  higher-confidence matcher — `_looks_like_committed_secret` — that never
  mis-flags security tooling like `secret-scrub.sh` or templates like
  `.env.example`). Runs via `asyncio.to_thread` like every other blocking
  call in that module; it grants no write capability, it only reads.
- The Architect surfaces these as ranked plan items (a committed secret is
  urgent human action; a deprecated action is an `infra_change` naming the
  exact file / `action@vN` / recommended version). Workflow and secret
  fixes are **never** `safe_to_autoimplement` — they route to a human,
  because CI/workflow files run with real secrets and a bad edit there is a
  credential-exfiltration path.
- **Built (always-on defensive gate)**: `scripts/repo_health_check.py` +
  `.github/workflows/repo-health.yml` run the same deprecated-action /
  committed-secret checks as a stdlib-only CI gate that **fails the build**
  the moment either appears — no OpenRouter, no `pip install`, so it works
  even without a key and independently of whether the Architect ever runs.
  This is the automatic counterpart to the Architect's awareness scan; the
  two baselines are kept in lockstep by a parity test
  (`tests/test_repo_health_script.py`). This is the change that would have
  caught the `upload-artifact@v3` breakage on the PR instead of after merge.
- **Built (richer awareness)**: `AGENT_FULL_SOURCE_VISIBILITY_ENABLED` now
  defaults **on** in `docker-compose.yml` (Phase 5d's flag), so the
  Architect plans against real source contents — the `_is_source_readable`
  secret denylist still applies unconditionally (never `.env`/keys/
  secrets). Real per-cycle OpenRouter token cost when a key is set; flip to
  false to return to the curated summary.
- **Built (environment cleanup/maintenance)**: `scripts/maintenance.sh`
  prunes regenerable caches (and, with `--deep`, build outputs), reports
  disk, and runs the health gate at the end — safe, idempotent housekeeping
  for a dev container / Codespace.

**Boundaries reaffirmed — unchanged, and load-bearing precisely because
this phase is about security:** agents still never push to or merge `main`
directly (`_assert_never_main`); still never read `.env`/key/secret-shaped
files (the `_is_source_readable` denylist is the real boundary, not the
flag); still never auto-implement `code_change`/`infra_change`; and the
auto-merge path (Phase 5c) stays scoped to allowlisted docs only. Giving an
agent that is reachable by untrusted input (chat, external public records)
unrestricted repo control or secret access would be the *vulnerability*,
not the defense — so it stays out, by design. Widening any of those
specific boundaries would be a further, separate written decision here,
with the abuse analysis spelled out, not a side effect of this phase.

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
