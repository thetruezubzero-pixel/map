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

# `git diff`/`--cached` are both blind to a brand-new file that was never
# `git add`ed -- confirmed live that a freshly-written untracked file
# containing one of the banned strings below got exit 0 (silently
# allowed) with only the two `git diff` calls above. A subagent using
# the Write tool doesn't stage its own output, so this isn't a corner
# case -- it's the default shape of a subagent's work. `git diff
# --no-index` against /dev/null renders an untracked file as a full
# addition without touching the index (unlike `git add -N`, so this
# stays a read-only check).
untracked_content=""
while IFS= read -r f; do
  [ -f "$f" ] || continue
  untracked_content="$untracked_content
$(git diff --no-index -- /dev/null "$f" 2>/dev/null)"
done < <(git ls-files --others --exclude-standard -- . ':(exclude)*.md' 2>/dev/null)

diff_content="$diff_content
$untracked_content"

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
