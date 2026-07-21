# Aether Sovereign OS

Geospatial intelligence platform, built incrementally. See
[`CLAUDE.md`](./CLAUDE.md) for working principles and
[`docs/architecture/ROADMAP.md`](./docs/architecture/ROADMAP.md) for phase
status and scope boundaries.

## Phase 1: Core gateway

- `apps/api/rust/gateway` — Rust/Axum API gateway
  - `GET /health` — service status
  - `GET /geocode?q=<query>&limit=<1-20>` — proxies OpenStreetMap Nominatim
  - Rate limiting (per-IP, `tower_governor`), User-Agent hygiene checks,
    and strict CORS, all scoped to hardening this service itself
- `data/schemas/postgres/001_init.sql` — PostGIS schema (`locations`,
  `research_entities`)
- `infra/docker/docker-compose.yml` — local dev stack

### Run locally

```sh
cp .env.example .env   # fill in POSTGRES_PASSWORD at minimum
docker compose -f infra/docker/docker-compose.yml --env-file .env up --build
curl http://localhost:8080/health
curl "http://localhost:8080/geocode?q=Eiffel+Tower"
```

### Develop the gateway directly

```sh
cd apps/api/rust
cargo check
cargo run -p aether-gateway   # reads .env from apps/api/rust/gateway/ or process env
```
