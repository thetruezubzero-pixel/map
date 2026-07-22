#!/usr/bin/env bash
# SubagentStop hook: blocks (exit 2) if the working diff contains anything
# that looks like a hardcoded secret. Uses detect-secrets if available,
# falls back to plain pattern matching otherwise.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 0

diff_content=$( { git diff HEAD 2>/dev/null; git diff --cached 2>/dev/null; } )

# `git diff`/`--cached` are both blind to a brand-new file that was never
# `git add`ed -- confirmed live that a fresh untracked file containing an
# AWS-shaped key got exit 0 (silently allowed) with only the two `git
# diff` calls above. Same fix as scope-guard.sh: render every untracked,
# non-ignored file as a full addition via `git diff --no-index` against
# /dev/null, which doesn't touch the index.
untracked_content=""
while IFS= read -r f; do
  [ -f "$f" ] || continue
  untracked_content="$untracked_content
$(git diff --no-index -- /dev/null "$f" 2>/dev/null)"
done < <(git ls-files --others --exclude-standard 2>/dev/null)

diff_content="$diff_content
$untracked_content"

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
  # Confirmed live (security review) that the original version of this
  # pattern only matched when "secret"/"api_key" sat immediately before
  # the assignment operator -- a real, common naming convention like
  # `AWS_SECRET_ACCESS_KEY = "..."` or `STRIPE_SECRET_KEY = "..."` has
  # other identifier characters in between and slipped through
  # undetected (reproduced: exit 0 on a file containing exactly that).
  # Now matches the keyword anywhere in the variable name, not just as
  # an exact prefix.
  '[A-Za-z0-9_]*(api[_-]?key|secret|token|password)[A-Za-z0-9_]*["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9_/+-]{16,}'
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
