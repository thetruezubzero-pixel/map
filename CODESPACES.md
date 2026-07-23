# Codespaces Setup Guide

Run Aether Sovereign OS on GitHub Codespaces for remote development on any device (iPhone, iPad, laptop).

## Quick Start (2 minutes)

1. **Create a Codespace**: Go to your repo's `Code` button → `Create codespace on main`
2. **Wait for container build** (~2-3 minutes for first-time build)
3. **Forward port 5173** and open it in your browser
4. **Map, search, and entity browsing work immediately** — no additional secrets needed

## Environment Variables (GitHub Codespaces Secrets)

Add these to your GitHub repo's **Settings → Codespaces → Codespaces Secrets** for each secret to be automatically available to all new Codespaces.

### Tier 1: Required — App refuses to start without these

#### `JWT_SECRET`
- **What it is**: Long random string for signing authentication tokens
- **Lifetime**: Fixed, never expires, never needs rotating
- **How to set**: Generate one with:
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
- **Why it matters**: Without this, the gateway and python-api won't start
- **Already correct in the repo?** No — `.env.example` has a placeholder `change-me-in-production`. You must generate a real one.

#### `NOMINATIM_USER_AGENT`
- **What it is**: Identifying text for Nominatim's usage policy (not a credential)
- **Example**: `YourApp/1.0 (contact: you@example.com)` — use your real email
- **Lifetime**: Fixed, never changes
- **Why it matters**: Nominatim (OpenStreetMap's geocoding service) blocks requests from placeholder domains
- **Already correct?** No — needs your real contact email

### Tier 2: Recommended — Core features work without these but fall back to placeholders

#### `VITE_MAPBOX_ACCESS_TOKEN`
- **What it is**: Free Mapbox account token
- **Lifetime**: Fixed, set once, done forever (free)
- **How to get**: Create account at https://account.mapbox.com/access-tokens/
- **Why it matters**: Without this, the map shows a "set your token" placeholder instead of a real map
- **Already correct?** No — `.env.example` is empty

#### `HEIRLOOM_DEVICE_KEY`
- **What it is**: 64-character hex string for encrypting agent weight snapshots (AES-256-GCM)
- **Lifetime**: Fixed, generated once
- **How to set**: Generate one with:
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
- **Why it matters**: Required for the "Export heirloom" button on the `/heirlooms` page to work
- **Already correct?** No — `.env.example` is empty

### Tier 3: **Genuinely Optional** — App behaves identically without these

#### `OPENROUTER_API_KEY`
- **What it is**: Real OpenRouter account with funded credits
- **Lifetime**: Ongoing — this is the **only secret that has a running cost**
- **When needed**: Only if you want the AI research pipeline (`/research`, `/swarm`, `/chat`) to actually call models
- **When to skip**: If you just want to browse the map and entity search
- **Already correct?** No — `.env.example` is empty (which is correct — leave it unset until you've funded an OpenRouter account)

#### `NEWSAPI_KEY` and `OPENCORPORATES_API_KEY`
- **What they are**: Free public-records source APIs
- **When needed**: Only if you want those specific data sources in the research pipeline
- **When to skip**: Fully optional — data retriever skips them gracefully if unset
- **Already correct?** Yes — `.env.example` has them empty, which is correct

## Step-by-Step Setup

### 1. Generate secrets (do this once, save them)

```bash
# Tier 1 secrets
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
HEIRLOOM_DEVICE_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Print them so you can copy into GitHub Codespaces secrets
echo "JWT_SECRET=$JWT_SECRET"
echo "HEIRLOOM_DEVICE_KEY=$HEIRLOOM_DEVICE_KEY"
```

### 2. Add to GitHub Codespaces Secrets

Go to your repo's **Settings → Codespaces → Codespaces Secrets** (or https://github.com/YOUR_OWNER/YOUR_REPO/settings/codespaces):

1. **Add `JWT_SECRET`**
   - Name: `JWT_SECRET`
   - Value: [paste the generated value from step 1]
   - Repository access: This repository only
   - Click "Add secret"

2. **Add `NOMINATIM_USER_AGENT`**
   - Name: `NOMINATIM_USER_AGENT`
   - Value: `YourApp/1.0 (contact: you@yourdomain.com)` — **use your real email**
   - Repository access: This repository only
   - Click "Add secret"

3. **Add `HEIRLOOM_DEVICE_KEY`**
   - Name: `HEIRLOOM_DEVICE_KEY`
   - Value: [paste the generated value from step 1]
   - Repository access: This repository only
   - Click "Add secret"

4. **Optionally add `VITE_MAPBOX_ACCESS_TOKEN`**
   - Create free Mapbox token: https://account.mapbox.com/access-tokens/
   - Name: `VITE_MAPBOX_ACCESS_TOKEN`
   - Value: [paste your Mapbox token]
   - Click "Add secret"

5. **Optionally add `OPENROUTER_API_KEY`**
   - Only if you've set up an OpenRouter account with funded credits
   - Name: `OPENROUTER_API_KEY`
   - Value: [paste your OpenRouter API key]
   - Click "Add secret"

### 3. Create a new Codespace

The secrets you just added will be automatically available to **new** Codespaces created after this point (not to existing ones).

- Go to **Code** button → **Create codespace on main**
- Wait for the container build (2-3 minutes)
- Once ready, GitHub will automatically forward port 5173

### 4. Open the app

GitHub shows forwarded port 5173 in the Ports tab or the VS Code notification. Click the link to open it.

## What Works Without API Keys?

✅ **Fully functional without any API keys:**
- Map pan/zoom and geocoding via Nominatim (one of the two required secrets)
- Entity search (by name, location)
- Entity detail panels
- Public records browsing (CIK, OpenCorporates ID, regulatory filings)
- All swarm agent dashboard pages

✅ **Fully functional without OPENROUTER_API_KEY:**
- `/research` page renders, but research jobs can't actually run
- `/swarm` page shows agent history and status
- `/architect` page shows project snapshots (read-only)
- `/chat` page renders, but won't get model responses

❌ **Requires OPENROUTER_API_KEY to work:**
- Submitting a research query (`POST /research`) with real model calls
- Chat responses (`POST /chat`)
- Autonomous Architect cycles (if `ARCHITECT_AUTO_COMMIT_ENABLED=true`)

## Troubleshooting

### Codespace is stuck on build

Sometimes the GitHub Actions runner is busy. Try creating a new Codespace a few minutes later.

### Port 5173 isn't showing up

The port forwarding may not have been automatic. In VS Code, open the Command Palette and run "Forward a Port" → type "5173".

### Docker Compose is taking forever

The first build of the full stack (postgres, redis, qdrant, elasticsearch, kafka, ksqldb, flink, gateway, python-api, frontend) can take 3-5 minutes. The second build (with cached layers) is ~30 seconds.

### I see an error in the browser but it doesn't match my JWT_SECRET or NOMINATIM_USER_AGENT

If you added secrets *after* creating the Codespace, they won't be available until you create a *new* Codespace. The old one won't pick them up.

## What's Available Beyond Codespaces?

For production deployment (beyond Codespaces development):
- See `docker-compose.yml` for the full local dev stack
- See `apps/gateway/Dockerfile`, `apps/web/Dockerfile`, `apps/api/python/Dockerfile` for individual service deployment
- All services are stateless; the only persistent layers are Postgres (with PostGIS), Redis, Qdrant, and Elasticsearch
- Scale horizontally: multiple gateway instances behind a load balancer, multiple python-api workers via `--workers` (currently single-worker, see apps/api/python/Dockerfile)

## Questions?

See `CLAUDE.md` for the full architectural overview, `ROADMAP.md` for development phases, and `.env.example` for all environment variable documentation.
