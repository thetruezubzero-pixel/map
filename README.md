# Aether Sovereign OS

A research platform for public business, property, and location records —
geocoding, geospatial/full-text search, entity resolution, and an
agent-assisted research pipeline over public records (OpenStreetMap,
NewsAPI/GDELT, OpenCorporates/SEC EDGAR, Census/USGS). See `CLAUDE.md` and
`ROADMAP.md` for architecture, scope, and phase history.

## Run it in a Codespace (recommended way to open this on a phone)

This repo has a `.devcontainer/devcontainer.json` that brings up the whole
stack (Postgres, Redis, Qdrant, the Rust gateway, the Python API, and the
web frontend) and forwards port 5173, which GitHub turns into a real HTTPS
URL you can open on any device, including a phone browser.

1. **Set two required secrets first** — go to this repo's
   **Settings → Secrets and variables → Codespaces** and add:
   - `JWT_SECRET` — any long random string (used to sign auth tokens)
   - `NOMINATIM_USER_AGENT` — a real identifying contact string, e.g.
     `YourApp/1.0 (contact: you@example.com)`. Nominatim's usage policy
     blocks generic/placeholder values.

   (Codespaces secrets are injected as environment variables automatically
   — `docker-compose.yml` reads both from the environment and refuses to
   start those services without them.)

2. **Open a Codespace** — from the repo's `Code` button, or from the
   GitHub mobile app: open this repo → the `...` menu → **Open with
   Codespaces** → **Create codespace**.

3. Wait for the container to build and `docker compose up` to finish
   starting (a minute or two on first launch). GitHub will prompt to open
   the forwarded port 5173 in your browser — accept it, or open the
   **Ports** tab and click the forwarded URL.

4. By default the forwarded port is private (only you, signed into
   GitHub, can open it). To share the link with someone else, open the
   **Ports** tab in the Codespace and change port 5173's visibility to
   **Public**.

If the stack didn't start automatically, run this from the Codespace's
terminal:

```bash
docker compose up -d postgres redis qdrant gateway python-api web
```

## Run it locally

```bash
cp .env.example .env   # fill in JWT_SECRET and NOMINATIM_USER_AGENT at minimum
docker compose up -d postgres redis qdrant gateway python-api web
```

Then open `http://localhost:5173`. See each app's own `.env.example`
(`apps/gateway`, `apps/web`, `apps/api/python`) for standalone (non-Docker)
runs.
