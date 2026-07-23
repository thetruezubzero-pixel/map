#!/usr/bin/env bash
#
# Bootstrap a working root .env for `docker compose up`, so a fresh
# Codespace (or `git clone` + open) starts the map/search stack on the
# FIRST try with zero manual secret entry.
#
# Design goals (read before editing):
#  1. NEVER weaken security. The `${JWT_SECRET:?...}` guards in
#     docker-compose.yml stay load-bearing (see CLAUDE.md). This script
#     does not remove them -- it just makes sure a real, strong value
#     exists so they pass legitimately instead of the stack aborting.
#  2. Auto-generate only the MACHINE-LOCAL secrets (no external account):
#     JWT_SECRET, HEIRLOOM_DEVICE_KEY. Cryptographically random -- strictly
#     better than a human pasting a placeholder.
#  3. Real-account keys (OPENROUTER_API_KEY, NEWSAPI_KEY, ...) are only
#     ever passed THROUGH from the environment (Codespaces secrets). Never
#     invented, never defaulted to a fake value -- the system degrades
#     gracefully without them, and inventing one would just produce a 401.
#  4. Idempotent. Safe to run on every create/start. An existing real
#     value (from the environment or a prior .env) is always preserved;
#     nothing already set is clobbered.
#
# EXTENDING THIS (it is meant to grow):
#  - New locally-generatable secret?  add its name to GENERATE_HEX_KEYS.
#  - New pass-through real-account key? add it to PASSTHROUGH_KEYS.
#  - New key with a sensible non-secret default? add a line in the
#    "sensible defaults" section near the bottom, following NOMINATIM_*.
#  Adding a key to .env.example alone is enough for it to appear in .env;
#  the lists below only control auto-population.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
ENV_EXAMPLE="${REPO_ROOT}/.env.example"

# --- extension points -------------------------------------------------
# Local secrets we can safely generate ourselves (32-byte hex each).
GENERATE_HEX_KEYS=(JWT_SECRET HEIRLOOM_DEVICE_KEY)

# Real-account keys: only copied in if already present in the environment
# (e.g. a Codespaces secret). Empty otherwise -- the app handles that.
PASSTHROUGH_KEYS=(
  OPENROUTER_API_KEY OPENROUTER_BASE_URL OPENROUTER_DEFAULT_MODEL
  OPENROUTER_FAST_MODEL OPENROUTER_FALLBACK_MODEL OPENROUTER_COORDINATOR_MODEL
  NEWSAPI_KEY OPENCORPORATES_API_KEY EDGAR_IDENTITY
  GITHUB_TOKEN GITHUB_REPO
  REDIS_PASSWORD
)

# Values that are known-placeholder (treated as "not really set").
is_placeholder() {
  case "$1" in
    "" | "change-me-in-production" | "your-"* | *"yourdomain"* | *"example.com"*) return 0 ;;
    *) return 1 ;;
  esac
}
# ----------------------------------------------------------------------

# Seed .env from the template on first run so every documented key + its
# explanatory comments are present; we then fill in values below.
if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"
  echo "bootstrap-env: created .env from .env.example"
fi

# Read the current value of KEY from .env (last assignment wins), or "".
get_env_var() {
  local key="$1"
  grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

# Set KEY=VALUE in .env: replace the existing assignment in place, or
# append if the key isn't present. Value is written literally.
set_env_var() {
  local key="$1" value="$2" tmp
  if grep -qE "^${key}=" "${ENV_FILE}"; then
    tmp="$(mktemp)"
    # Use awk (not sed) so slashes/special chars in the value are safe.
    awk -v k="${key}" -v v="${value}" \
      'BEGIN{done=0} $0 ~ "^" k "=" && !done {print k "=" v; done=1; next} {print}' \
      "${ENV_FILE}" > "${tmp}"
    mv "${tmp}" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

gen_hex() { python3 -c "import secrets; print(secrets.token_hex(32))"; }

# Resolve a key's value with precedence: live environment (Codespaces
# secret) > existing real .env value > (caller-provided fallback). Sets
# the resolved value back into .env. Returns the resolved value.
resolve_into_env() {
  local key="$1" fallback="${2-}" env_val file_val resolved
  env_val="$(printf '%s' "${!key-}")"
  file_val="$(get_env_var "${key}")"
  if ! is_placeholder "${env_val}"; then
    resolved="${env_val}"
  elif ! is_placeholder "${file_val}"; then
    resolved="${file_val}"
  else
    resolved="${fallback}"
  fi
  set_env_var "${key}" "${resolved}"
  printf '%s' "${resolved}"
}

# 1. Locally-generatable secrets: keep any real existing value, else mint.
for key in "${GENERATE_HEX_KEYS[@]}"; do
  existing="$(resolve_into_env "${key}" "")"
  if is_placeholder "${existing}"; then
    set_env_var "${key}" "$(gen_hex)"
    echo "bootstrap-env: generated ${key}"
  fi
done

# 2. Pass-through real-account keys: env wins, else keep whatever's there.
for key in "${PASSTHROUGH_KEYS[@]}"; do
  resolve_into_env "${key}" "$(get_env_var "${key}")" >/dev/null
done

# 3. Sensible non-secret defaults (extend here as the stack grows) -------
# Nominatim needs a REAL, identifying contact -- placeholder domains get
# blocked. Derive one from the Codespace's GitHub user when we can, so
# geocoding works out of the box without the operator thinking about it.
gh_user="${GITHUB_USER:-codespace}"
nominatim_default="AetherSovereignOS/1.0 (contact: ${gh_user}@users.noreply.github.com)"
resolve_into_env "NOMINATIM_USER_AGENT" "${nominatim_default}" >/dev/null
# -----------------------------------------------------------------------

echo "bootstrap-env: .env ready ($(grep -cE '^[A-Z].*=' "${ENV_FILE}") keys)"
