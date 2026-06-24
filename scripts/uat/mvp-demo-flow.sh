#!/usr/bin/env bash
# MVP 10-step demo flow — programmatic UAT (stdlib Python + curl when services are up).
# Usage: ANSWER_SERVICE_URL=http://127.0.0.1:8088 API_BASE=http://127.0.0.1:3000/v1 ./scripts/uat/mvp-demo-flow.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${PYTHONPATH:-src}"
export ANSWER_SERVICE_URL="${ANSWER_SERVICE_URL:-http://127.0.0.1:8088}"
export API_BASE="${API_BASE:-http://127.0.0.1:3000/v1}"
export DEMO_TENANT="${DEMO_TENANT:-demo}"
export DEMO_USER="${DEMO_USER:-alice}"

echo "[uat] Tier A hard gates"
scripts/gate.sh a

echo "[uat] Python UAT scenarios (MFG + X)"
python3 -m unittest tests.uat.test_industry_usecases tests.manufacturing.test_mvp_completion_api -q

echo "[uat] MVP flow smoke (requires live API — skipped if unreachable)"
if curl -sf "${API_BASE%/v1}/health" >/dev/null 2>&1 || curl -sf "$ANSWER_SERVICE_URL/health" >/dev/null 2>&1; then
  echo "  live API detected — run manual browser UAT at /orgselect then /sources/new -> /reviews/documents -> /"
else
  echo "  API not running — stdlib UAT only (start stack for full 10-step browser demo)"
fi

echo "[uat] DONE"
