#!/usr/bin/env bash
# SubagentStop hook: blocks (exit 2) if the diff touches an explicit
# ROADMAP.md non-goal. These require a written scope decision from the
# repo owner in ROADMAP.md before any implementation lands -- see
# ROADMAP.md "Explicit non-goals".
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 0

# Markdown is excluded: CLAUDE.md/ROADMAP.md are expected to name these
# banned terms in prose (that's how the ban gets documented) -- this
# guard is about code implementing the feature, not docs describing why
# it's banned.
diff_content=$( { git diff HEAD -- . ':(exclude)*.md' 2>/dev/null; git diff --cached -- . ':(exclude)*.md' 2>/dev/null; } )

if [ -z "$diff_content" ]; then
  exit 0
fi

banned=(
  "entity_type[^\n]{0,20}['\"]person['\"]"
  "EntityType\.person"
  "class[[:space:]]+Person\b"
  "bluetooth[^\n]{0,25}(scan|discover|beacon)"
  "wifi[^\n]{0,25}(scan|discover)"
  "\bimsi\b"
  "mac[_-]?address[^\n]{0,25}(harvest|track|scan)"
  "opsec[^\n]{0,25}(decoy|evasion)"
  "fingerprint[^\n]{0,25}randomiz"
  "\bzk-snark"
  "\bdid:[a-z]+:"
)

hits=""
for p in "${banned[@]}"; do
  m=$(echo "$diff_content" | grep -inE "$p" || true)
  if [ -n "$m" ]; then
    hits="$hits
[pattern: $p]
$m"
  fi
done

if [ -n "$hits" ]; then
  echo "[scope-guard] BLOCKED: diff touches an explicit ROADMAP.md non-goal:$hits

See ROADMAP.md 'Explicit non-goals'. These need a written scope decision
from the repo owner, documented in ROADMAP.md with rationale and
safeguards, before implementation -- not a subagent's call to make." >&2
  exit 2
fi

exit 0
