#!/usr/bin/env bash
#
# RT1 local dependency smoke:
#   docker compose up for postgres+pgvector, MinIO, LocalStack SQS, and trace-sink.
#
# Exit codes:
#   0 = stack booted and checks passed
#   1 = stack boot/check failed on a Docker-capable host
#   2 = Docker/Compose or nested-container capability unavailable in this environment

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-infra/docker-compose.yml}"
KEEP_STACK="${KEEP_STACK:-0}"
TRACE_SINK_HEALTH_URL="${TRACE_SINK_HEALTH_URL:-http://127.0.0.1:13133/}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not on PATH." >&2
  exit 2
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not reachable." >&2
  exit 2
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 2
fi

compose=(docker compose -f "$COMPOSE_FILE")

cleanup() {
  if [[ "$KEEP_STACK" != "1" ]]; then
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

"${compose[@]}" config >/dev/null

if ! "${compose[@]}" up -d --wait postgres minio localstack trace-sink; then
  echo "docker compose up failed." >&2
  if ! unshare -m true >/dev/null 2>&1; then
    echo "This environment cannot create a mount namespace (unshare -m failed)." >&2
    echo "Run RT1 on a Docker host or a privileged container with nested containers enabled." >&2
    exit 2
  fi
  exit 1
fi

vector_present="$("${compose[@]}" exec -T postgres psql -U raku -d raku -tAc \
  "SELECT 1 FROM pg_extension WHERE extname='vector';")"
if [[ "$vector_present" != "1" ]]; then
  echo "pgvector extension was not available in the compose Postgres." >&2
  exit 1
fi

"${compose[@]}" exec -T localstack awslocal sqs list-queues | grep -q "raku-ingest"
"${compose[@]}" exec -T minio mc ready local >/dev/null

python - <<PY
from urllib.request import urlopen

with urlopen("${TRACE_SINK_HEALTH_URL}", timeout=10) as response:
    if response.status >= 400:
        raise SystemExit(f"trace-sink health returned {response.status}")
PY

echo "Docker compose local dependency smoke GREEN"
