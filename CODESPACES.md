# Codespaces Setup Guide

Run Aether Sovereign OS on GitHub Codespaces for remote development on any device (iPhone, iPad, laptop).

## Quick Start (2 minutes)

1. **Create a Codespace**: Go to your repo's `Code` button → `Create codespace on main`
2. **Wait for container build** (~2-3 minutes for first-time build). On
   creation, `.devcontainer/bootstrap-env.sh` auto-generates the local
   secrets and `.devcontainer/start.sh` brings the stack up and waits
   until the frontend is actually serving.
3. **Forward port 5173** and open it in your browser
4. **Map, search, and entity browsing work immediately** — no secrets to set

## Environment Variables (GitHub Codespaces Secrets)

**You don't need to set anything to get started.** The bootstrap script
generates the machine-local secrets on first boot, and any secret you *do*
add as a Codespaces Secret (**Settings → Codespaces → Codespaces Secrets**)
always takes precedence over the generated one — the bootstrap never
overwrites an operator-provided value.

### Tier 1: Auto-generated for you — nothing to do

#### `JWT_SECRET`
- **What it is**: Long random string for signing authentication tokens
- **Handled how**: `bootstrap-env.sh` generates a cryptographically random
  value on first boot. The `${JWT_SECRET:?...}` guard in
  `docker-compose.yml` stays in force — it now passes because a real value
  exists, rather than aborting the stack.
- **Set it yourself only if**: you want a *specific* value shared across
  environments — add it as a Codespaces Secret and it wins over the
  generated one.

#### `NOMINATIM_USER_AGENT`
- **What it is**: Identifying text for Nominatim's usage policy (not a credential)
- **Handled how**: defaulted to `AetherSovereignOS/1.0 (contact:
  <your-github-user>@users.noreply.github.com)` — a real, non-placeholder
  contact so Nominatim doesn't block geocoding.
- **Set it yourself only if**: you'd rather use a different contact address.

#### `HEIRLOOM_DEVICE_KEY`
- **What it is**: 64-character hex string for encrypting agent weight snapshots (AES-256-GCM)
- **Handled how**: auto-generated on first boot, so the "Export heirloom"
  button on `/heirlooms` works out of the box.
- **Set it yourself only if**: you need the same key across environments to
  decrypt heirlooms exported elsewhere.

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

4. **Optionally add `OPENROUTER_API_KEY`**
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
