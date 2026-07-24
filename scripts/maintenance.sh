#!/usr/bin/env bash
#
# Environment cleanup & maintenance (ROADMAP.md Phase 11).
#
# Safe, idempotent housekeeping for a dev container / Codespace: prunes
# regenerable caches and build artifacts to reclaim disk, reports disk
# usage, and runs the repo-health/security gate at the end so a
# maintenance pass also tells you if any deprecated action or committed
# secret has crept in.
#
# Default run only removes CACHES (always safe -- Python bytecode, tool
# caches). Pass --deep to also remove BUILD OUTPUTS (target/, dist/,
# node_modules) -- those are regenerable too, but removing them forces a
# rebuild/reinstall next time, so it's opt-in.
#
# Usage:
#   bash scripts/maintenance.sh            # caches only
#   bash scripts/maintenance.sh --deep     # + build outputs (forces rebuilds)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEEP=0
[[ "${1:-}" == "--deep" ]] && DEEP=1

echo "maintenance: repo root = ${REPO_ROOT}"
echo "maintenance: disk before:"
df -h "${REPO_ROOT}" | tail -1 || true

# --- caches (always safe to remove; regenerated on demand) -------------
echo "maintenance: pruning caches..."
find "${REPO_ROOT}" -type d \
  \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.mypy_cache' -o -name '.ruff_cache' \) \
  -not -path '*/node_modules/*' -prune -exec rm -rf {} + 2>/dev/null || true
find "${REPO_ROOT}" -type f -name '*.pyc' -not -path '*/node_modules/*' -delete 2>/dev/null || true
find "${REPO_ROOT}" -type f -name '*.log' -path '*/apps/ios-app/*' -delete 2>/dev/null || true

# --- build outputs (regenerable, but opt-in since removal forces rebuilds)
if [[ "${DEEP}" -eq 1 ]]; then
  echo "maintenance: --deep -- removing build outputs (target/, dist/, node_modules/)..."
  rm -rf "${REPO_ROOT}/apps/gateway/target" 2>/dev/null || true
  rm -rf "${REPO_ROOT}/apps/web/dist" 2>/dev/null || true
  rm -rf "${REPO_ROOT}/apps/web/node_modules" 2>/dev/null || true
fi

echo "maintenance: disk after:"
df -h "${REPO_ROOT}" | tail -1 || true

# --- security/health gate ----------------------------------------------
echo "maintenance: running repo-health/security scan..."
if command -v python3 >/dev/null 2>&1; then
  python3 "${REPO_ROOT}/scripts/repo_health_check.py" || {
    echo "maintenance: ⚠️  repo-health scan found issues (see above)." >&2
    exit 1
  }
else
  echo "maintenance: python3 not found -- skipping health scan." >&2
fi

echo "maintenance: done."
