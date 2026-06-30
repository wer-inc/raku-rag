#!/usr/bin/env bash
# Run the internal ChatBot golden scenario scorecard against local demo or a deployed /v1 API.
#
# Local:
#   bash scripts/demo/chatbot_golden_scorecard.sh
#
# Deployed/stg with an operator-issued token:
#   RAKU_PROD_BASE_URL=http://example.elb.amazonaws.com/v1 \
#   RAKU_PROD_BEARER_TOKEN="$(... issue Cognito token ...)" \
#   bash scripts/demo/chatbot_golden_scorecard.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATASET="${CHATBOT_GOLDEN_DATASET:-$ROOT/scripts/demo/chatbot_golden_scenarios.json}"

python3 "$ROOT/scripts/demo/chatbot_golden_scenarios.py" \
  --dataset "$DATASET" \
  "$@"
