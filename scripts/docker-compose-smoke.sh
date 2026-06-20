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

# `up --wait` only blocks on container healthchecks, which can go green BEFORE the one-shot init
# scripts finish (Postgres `db/init` CREATE EXTENSION vector; LocalStack `ready.d` queue creation).
# Poll each post-boot dependency instead of checking once, so the smoke is deterministic rather than
# racing the init (the intermittent exit-255/exit-1 seen when an exec hit a not-yet-ready service).
READINESS_TIMEOUT="${READINESS_TIMEOUT:-90}"
retry() {
  # retry <desc> <fn>: run <fn> until it succeeds or READINESS_TIMEOUT seconds elapse.
  local desc="$1" fn="$2" deadline=$((SECONDS + READINESS_TIMEOUT))
  until "$fn"; do
    if ((SECONDS >= deadline)); then
      echo "timed out after ${READINESS_TIMEOUT}s waiting for: ${desc}" >&2
      return 1
    fi
    sleep 2
  done
}

pgvector_ready() {
  local present
  present="$("${compose[@]}" exec -T postgres psql -U raku -d raku -tAc \
    "SELECT 1 FROM pg_extension WHERE extname='vector';" 2>/dev/null || true)"
  [[ "$(echo "$present" | tr -d '[:space:]')" == "1" ]]
}
if ! retry "pgvector extension" pgvector_ready; then
  echo "pgvector extension was not available in the compose Postgres." >&2
  exit 1
fi

ingest_queue_ready() {
  "${compose[@]}" exec -T localstack awslocal sqs list-queues 2>/dev/null | grep -q "raku-ingest"
}
if ! retry "raku-ingest SQS queue" ingest_queue_ready; then
  echo "raku-ingest SQS queue was not created on LocalStack." >&2
  exit 1
fi

minio_ready() { "${compose[@]}" exec -T minio mc ready local >/dev/null 2>&1; }
if ! retry "MinIO readiness" minio_ready; then
  echo "MinIO did not report ready." >&2
  exit 1
fi

trace_sink_ready() {
  python3 - <<PY
from urllib.request import urlopen

try:
    with urlopen("${TRACE_SINK_HEALTH_URL}", timeout=5) as response:
        raise SystemExit(0 if response.status < 400 else 1)
except SystemExit:
    raise
except Exception:
    raise SystemExit(1)
PY
}
if ! retry "trace-sink health" trace_sink_ready; then
  echo "trace-sink health check did not pass at ${TRACE_SINK_HEALTH_URL}." >&2
  exit 1
fi

echo "Docker compose local dependency smoke GREEN"
