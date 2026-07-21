# Roadmap

Aether Sovereign OS is being built incrementally. Each phase below only
starts once the previous one is working and the user has approved the next
slice of scope — this file tracks intent, not a commitment to build
everything listed.

## Status

- [x] **Phase 1 — Core gateway**: repo scaffold, Rust/Axum API gateway
  (`/health`, `/geocode` via Nominatim), rate limiting + bot detection +
  strict CORS on the gateway itself, PostgreSQL/PostGIS schema, Docker
  Compose local dev.
- [ ] Phase 2 — React frontend with map rendering and multi-provider
  geocoding fallback (additional providers added only once API keys are
  supplied via env vars).
- [ ] Phase 3 — Multi-agent research orchestration (public-records
  sources only, with a compliance/PII-blocking validator).
- [ ] Phase 4 — Data ingestion + streaming pipeline for change detection.
- [ ] Phase 5 — Hybrid search (vector + keyword + geospatial).
- [ ] Phase 6 — Hardware integration layer, scoped to devices the operator
  owns and that explicitly opt in (consented pairing only — no ambient
  scanning of third-party devices, no captive-portal bypass on networks
  not controlled by the operator).
- [ ] Phase 7 — Blockchain-backed device identity/attestation.
- [ ] Phase 8 — Extended defensive security (beyond the Phase 1 gateway
  hardening) — scoped case by case to protecting infrastructure the
  operator controls, not to evading third-party monitoring.
- [ ] Phase 9 — Compliance/audit dashboard.
- [ ] Phase 10 — Mobile app.

## Notes on scope boundaries

A few subsystems in the original design doc are dual-use and are
intentionally scoped narrowly:

- **Defensive security / OPSEC**: limited to hardening services this
  project operates (rate limiting, bot detection, CORS, anomaly logging).
  Not client-side fingerprint spoofing, traffic obfuscation, or evasion of
  third-party monitoring.
- **Hardware connectivity (Bluetooth/WiFi/cellular)**: limited to devices
  the operator owns and that explicitly opt in. No ambient scanning of
  bystander devices, no unauthorized network access.

Any change to these boundaries needs explicit sign-off before
implementation.
