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
  # Widened to also capture the host after `@`: the per-value exclusion
  # below only sees the matched substring, so it needs the hostname
  # visible to recognize a legitimate `aether:aether@postgres` local
  # placeholder (without it, the exclusion's host alternation could never
  # match and a real credential-in-URL to a local host would be wrongly
  # flagged, or vice-versa).
  '://[^/[:space:]:]+:[^/[:space:]@]+@[^/[:space:]:]+'
)

# Local-only dev defaults (localhost/compose-service hosts, the
# aether:aether/airflow:airflow placeholder creds used throughout
# .env.example and docker-compose.yml) aren't a leak risk.
placeholder_re='your-|change-me|dev-only|example\.com|placeholder|\$\{|<[a-z-]+>|://(aether|airflow):(aether|airflow)@(localhost|postgres|airflow-postgres)'

hits=""
for p in "${patterns[@]}"; do
  matches=$(echo "$diff_content" | grep -inE -e "$p" || true)
  [ -z "$matches" ] && continue

  # Exclude per-MATCHED-VALUE, not per-line: a security review found the
  # original whole-line `grep -viE` excluded a real secret whenever a
  # placeholder token happened to appear anywhere else on the same line
  # (e.g. a real AWS key with a trailing `# see example.com` comment was
  # silently allowed). Extract just the matched substring and test only
  # that against the placeholder list.
  m=""
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    value=$(echo "$line" | grep -oiE -e "$p" | tail -1)
    if echo "$value" | grep -qiE "$placeholder_re"; then
      continue
    fi
    m="$m
$line"
  done <<< "$matches"

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
