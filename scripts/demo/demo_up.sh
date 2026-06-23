#!/usr/bin/env bash
# One-command PoC demo bring-up: Postgres -> answer-service (clean reset + curated seed) ->
# NestJS API -> Next.js web. Idempotent; safe to re-run. Logs under /tmp/raku-demo/.
#
#   bash scripts/demo/demo_up.sh
#   open http://localhost:${WEB_PORT:-3002}   (login: any → org select → ホーム)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

PGURL="${POSTGRES_URL:-postgresql://raku:raku@127.0.0.1:5432/raku_parity}"
AS_PORT="${AS_PORT:-8088}"
API_PORT="${API_PORT:-3000}"
WEB_PORT="${WEB_PORT:-3002}"
THRESH="${RAKU_DEFAULT_SCORE_THRESHOLD:-0.4}"
LOG=/tmp/raku-demo
mkdir -p "$LOG"

say() { printf '\n\033[1;36m[demo-up]\033[0m %s\n' "$*"; }
wait_tcp() { for _ in $(seq 1 "${3:-40}"); do (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null && return 0; sleep 1; done; return 1; }
wait_http() { for _ in $(seq 1 "${3:-60}"); do [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 "$1" 2>/dev/null)" = "200" ] && return 0; sleep 1; done; return 1; }

say "1/5 Postgres ($PGURL)"
PGPASSWORD="${PGPASSWORD:-raku}" psql "$PGURL" -tAc 'select 1' >/dev/null || { echo "Postgres unreachable — start it first (infra/docker-compose.yml or native)"; exit 1; }

say "2/5 answer-service :$AS_PORT (clean reset + demo tenant)"
fuser -k "${AS_PORT}"/tcp 2>/dev/null || true; sleep 1
RAKU_DEFAULT_SCORE_THRESHOLD="$THRESH" POSTGRES_URL="$PGURL" PYTHONPATH=src \
  nohup python3 apps/answer-service/server.py --reset-demo-db --seed --port "$AS_PORT" >"$LOG/answer-service.log" 2>&1 &
wait_tcp 127.0.0.1 "$AS_PORT" 40 || { echo "answer-service failed; see $LOG/answer-service.log"; tail -20 "$LOG/answer-service.log"; exit 1; }

say "3/5 seed curated 東洋精機 knowledge base (18 docs)"
ANSWER_SERVICE_URL="http://127.0.0.1:${AS_PORT}" POSTGRES_URL="$PGURL" bash "$HERE/demo_seed.sh"

say "4/5 NestJS API :$API_PORT"
API_MAIN="apps/api/dist/apps/api/src/main"
[ -f "$API_MAIN.js" ] || { echo "building API…"; npm run build --workspace @raku-rag/api >/"$LOG"/api-build.log 2>&1; }
fuser -k "${API_PORT}"/tcp 2>/dev/null || true; sleep 1
API_PORT="$API_PORT" ANSWER_SERVICE_URL="http://127.0.0.1:${AS_PORT}" \
  nohup node --enable-source-maps "$API_MAIN" >"$LOG/api.log" 2>&1 &
wait_http "http://localhost:${API_PORT}/v1/health" 40 || { echo "API failed; see $LOG/api.log"; tail -20 "$LOG/api.log"; exit 1; }

say "5/5 Next.js web :$WEB_PORT (dev)"
fuser -k "${WEB_PORT}"/tcp 2>/dev/null || true; sleep 1
WEB_PORT="$WEB_PORT" nohup npm run dev:web >"$LOG/web.log" 2>&1 &
wait_http "http://localhost:${WEB_PORT}/" 90 || { echo "web failed; see $LOG/web.log"; tail -20 "$LOG/web.log"; exit 1; }

cat <<EOF

\033[1;32m✓ Demo is up.\033[0m  Open:  http://localhost:${WEB_PORT}/
  Logs: $LOG/{answer-service,api,web}.log
  Demo script + tested queries: docs/DEMO.md
EOF
