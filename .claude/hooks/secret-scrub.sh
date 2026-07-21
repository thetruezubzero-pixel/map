#!/usr/bin/env bash
# SubagentStop hook: blocks (exit 2) if the working diff contains anything
# that looks like a hardcoded secret. Uses detect-secrets if available,
# falls back to plain pattern matching otherwise.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 0

diff_content=$( { git diff HEAD 2>/dev/null; git diff --cached 2>/dev/null; } )

if [ -z "$diff_content" ]; then
  exit 0
fi

if command -v detect-secrets >/dev/null 2>&1; then
  findings=$(echo "$diff_content" | detect-secrets scan --string 2>/dev/null || true)
  if echo "$findings" | grep -q '"is_secret": true\|Secret Type'; then
    echo "[secret-scrub] BLOCKED: detect-secrets flagged possible secret(s):" >&2
    echo "$findings" >&2
    exit 2
  fi
  exit 0
fi

patterns=(
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  'AKIA[0-9A-Z]{16}'
  'api[_-]?key["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9_-]{16,}'
  'secret["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9_-]{16,}'
  '://[^/[:space:]:]+:[^/[:space:]@]+@'
)

hits=""
for p in "${patterns[@]}"; do
  # Local-only dev defaults (localhost/compose-service hosts, the
  # aether:aether/airflow:airflow placeholder creds used throughout
  # .env.example and docker-compose.yml) aren't a leak risk -- exclude
  # them so this doesn't trip on every doc/config change that mentions
  # the standard local DATABASE_URL.
  m=$(echo "$diff_content" | grep -inE -e "$p" | grep -viE 'your-|change-me|dev-only|example\.com|placeholder|\$\{|<[a-z-]+>|://(aether|airflow):(aether|airflow)@(localhost|postgres|airflow-postgres)' || true)
  if [ -n "$m" ]; then
    hits="$hits
[pattern: $p]
$m"
  fi
done

if [ -n "$hits" ]; then
  echo "[secret-scrub] BLOCKED: possible secret(s) found in diff:$hits" >&2
  exit 2
fi

exit 0
