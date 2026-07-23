#!/usr/bin/env bash
#
# Bring up the core map/search/API stack and wait until the frontend is
# actually serving before handing control back -- so the forwarded port
# opens to a working app, not a connection-refused page.
#
# Only the 6 core services start here (postgres, redis, qdrant, gateway,
# python-api, web). The heavy Phase-4 streaming stack (kafka, ksqldb,
# flink, elasticsearch, schema-registry) and airflow are intentionally
# left out of the default boot -- start them explicitly when you need
# them: `docker compose up -d kafka ksqldb flink-jobmanager ...`.
#
# EXTENDING: to add a service to the default boot, append it to
# CORE_SERVICES below.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

CORE_SERVICES=(postgres redis qdrant gateway python-api web)
WEB_URL="http://localhost:5173"
READY_TIMEOUT_SECS=180

# Make sure a valid .env exists before compose reads its `${VAR:?}` guards.
bash "${REPO_ROOT}/.devcontainer/bootstrap-env.sh"

echo "start: bringing up ${CORE_SERVICES[*]} ..."
docker compose up -d "${CORE_SERVICES[@]}"

echo -n "start: waiting for the frontend at ${WEB_URL} "
deadline=$(( $(date +%s) + READY_TIMEOUT_SECS ))
until curl -fsS -o /dev/null "${WEB_URL}" 2>/dev/null; do
  if [[ $(date +%s) -ge ${deadline} ]]; then
    echo ""
    echo "start: frontend did not respond within ${READY_TIMEOUT_SECS}s." >&2
    echo "start: check 'docker compose ps' and 'docker compose logs web gateway'." >&2
    exit 1
  fi
  echo -n "."
  sleep 3
done

echo ""
echo "start: ✅ up and serving. Open the forwarded port 5173 to use the map."
