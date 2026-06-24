#!/usr/bin/env bash
# Wait for the answer-service TCP port, then seed the curated 東洋精機 demo KB (18 docs + trouble-case
# graphs). Invoked by raku-seed.service after raku-answer.service starts. Reads AS_PORT /
# RAKU_INTERNAL_AUTH_SECRET / POSTGRES_URL from the systemd EnvironmentFile (/etc/raku-rag.env).
set -euo pipefail
cd "$(cd "$(dirname "$0")/../.." && pwd)"   # repo root

PORT="${AS_PORT:-8088}"
for _ in $(seq 1 30); do
  (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null && break
  sleep 1
done

ANSWER_SERVICE_URL="http://127.0.0.1:${PORT}" bash scripts/demo/demo_seed.sh
