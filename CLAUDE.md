# Aether Sovereign OS

Unified geospatial intelligence platform: multi-provider mapping, public-records
research, and a defensive security gateway. Built incrementally in phases —
see `docs/architecture/ROADMAP.md` for the full plan and current status.

## Principles

**Think Before Coding.** Understand the existing code and the actual
requirement before writing anything. Don't scaffold for a phase that hasn't
started.

**Simplicity First.** Prefer the plain solution. Three similar lines beat a
premature abstraction. No speculative config, no unused feature flags.

**Surgical Changes.** Touch only what the task requires. Don't refactor or
"clean up" unrelated code as a side effect of an unrelated change.

**Goal-Driven Execution.** Every subsystem in this repo must map to a phase
in the roadmap with a concrete, testable outcome. If a feature can't be
described as "this endpoint does X, verified by Y," it doesn't belong yet.

## Current phase: Phase 1 — Core Gateway

Implemented:
- `apps/api/rust/gateway` — Axum API gateway: `/health`, `/geocode`
  (proxies OpenStreetMap Nominatim only — no paid map providers wired up yet)
- Rate limiting, basic bot detection, and strict CORS on the gateway
  (defensive hardening of this service only — not client-side evasion tooling)
- `data/schemas/postgres` — PostGIS schema (locations, research_entities)
- `infra/docker/docker-compose.yml` — local dev: gateway + Postgres/PostGIS

Not yet implemented (future phases, do not scaffold speculatively): frontend,
additional map providers, AI agent orchestration, streaming pipeline, hybrid
search, hardware abstraction layer, blockchain identity, compliance
automation. See the roadmap doc before starting any of these.

## Working in this repo

- Rust gateway lives under `apps/api/rust/`. Run `cargo check` /
  `cargo test` from that directory before committing changes to it.
- Secrets and API keys are always read from environment variables
  (see `.env.example`). Never hardcode a key or commit a `.env` file.
- Bring up local dev with `docker compose -f infra/docker/docker-compose.yml up`.
