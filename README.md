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

1. **Secrets are handled for you on first boot — nothing to set up-front.**
   `.devcontainer/bootstrap-env.sh` runs automatically when the Codespace
   is created and generates the machine-local secrets so the stack comes
   up on the first try:
   - `JWT_SECRET` — auto-generated (cryptographically random). You only
     need to set it yourself (as a Codespaces secret) if you want a
     *specific* value shared across environments.
   - `HEIRLOOM_DEVICE_KEY` — auto-generated too, so the `/heirlooms`
     "Export heirloom" button works out of the box.
   - `NOMINATIM_USER_AGENT` — defaulted to a real, identifying contact
     derived from your GitHub username, so geocoding isn't blocked.

   The only secrets you'd ever add yourself (**Settings → Secrets and
   variables → Codespaces**) are the ones tied to a real external account,
   and every one of them is optional — the map, search, and entity
   browsing work fully without any of them:
   - `OPENROUTER_API_KEY` (optional) — enables the AI research side
     (`POST /research`, the `/swarm` dashboard, `/chat`). Without it those
     features degrade gracefully. Not free — needs funded credits.
   - `NEWSAPI_KEY` / `OPENCORPORATES_API_KEY` (optional) — widen which
     public-record sources the research agents pull from. Skipped if unset.

   Any secret you *do* set as a Codespaces secret always wins over the
   auto-generated value — the bootstrap never overwrites an operator-
   provided one, and never invents a real-account key.

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
bash .devcontainer/bootstrap-env.sh   # generates .env with local secrets (idempotent)
docker compose up -d postgres redis qdrant gateway python-api web
```

(You can still `cp .env.example .env` and edit by hand if you prefer — the
bootstrap just automates the machine-local secrets. Set `OPENROUTER_API_KEY`
in `.env` if you want the AI research pipeline to make real model calls.)

Then open `http://localhost:5173`. See each app's own `.env.example`
(`apps/gateway`, `apps/web`, `apps/api/python`) for standalone (non-Docker)
runs.
