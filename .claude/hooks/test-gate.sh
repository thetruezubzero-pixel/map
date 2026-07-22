#!/usr/bin/env bash
# SubagentStop hook: runs the test/build step for whichever subproject a
# subagent actually touched. Blocks (exit 2) on failure so a subagent
# can't report success with broken code.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 0

changed=$( { git diff --name-only HEAD 2>/dev/null; git diff --cached --name-only 2>/dev/null; git status --porcelain 2>/dev/null | awk '{print $2}'; } | sort -u)

fail=0

if echo "$changed" | grep -q '^apps/gateway/'; then
  echo "[test-gate] apps/gateway changed -- running cargo check" >&2
  if ! (cd apps/gateway && cargo check --quiet 2>&1); then
    fail=1
  fi
fi

if echo "$changed" | grep -q '^apps/web/'; then
  if [ -d apps/web/node_modules ]; then
    echo "[test-gate] apps/web changed -- running npm run build" >&2
    if ! (cd apps/web && npm run build --silent 2>&1); then
      fail=1
    fi
    if [ -f apps/web/package.json ] && grep -q '"test"' apps/web/package.json; then
      echo "[test-gate] apps/web changed -- running npm test" >&2
      if ! (cd apps/web && npm test --silent -- --run 2>&1); then
        fail=1
      fi
    fi
  else
    echo "[test-gate] apps/web changed but node_modules missing -- skipping (run npm install first)" >&2
  fi
fi

if echo "$changed" | grep -q '^apps/api/python/'; then
  if [ -d apps/api/python/.venv ]; then
    echo "[test-gate] apps/api/python changed -- running pytest" >&2
    if ! (cd apps/api/python && . .venv/bin/activate && python -m pytest -q 2>&1); then
      fail=1
    fi
  else
    echo "[test-gate] apps/api/python changed but .venv missing -- skipping (create venv first)" >&2
  fi
fi

if [ "$fail" -ne 0 ]; then
  echo "[test-gate] BLOCKED: one or more test/build steps failed. Fix before finishing." >&2
  exit 2
fi

exit 0
