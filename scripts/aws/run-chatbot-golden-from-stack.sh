#!/usr/bin/env bash
#
# Run the ChatBot golden scorecard against a deployed CDK stack.
#
# Usage:
#   RAKU_CHATBOT_SMOKE_APPROVED=yes \
#   RAKU_SMOKE_USERNAME='user@example.com' RAKU_SMOKE_PASSWORD='...' \
#   STACK=RakuRag-stg AWS_REGION=ap-northeast-1 \
#   bash scripts/aws/run-chatbot-golden-from-stack.sh
#
# Optional:
#   CHATBOT_GOLDEN_DATASET     Scenario dataset path.
#   CHATBOT_GOLDEN_OUTPUT      JSON output path.
#   RAKU_PROD_BASE_URL         Override http://<ALB>/v1 derived from stack outputs.
#   RAKU_CHATBOT_EVAL_PROFILE  Scorecard profile label.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STACK="${STACK:-RakuRag-sales}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-1}}"
AWS=(aws --region "$REGION")

if [[ "${RAKU_CHATBOT_SMOKE_APPROVED:-}" != "yes" && "${RAKU_PROD_SMOKE_APPROVED:-}" != "yes" ]]; then
  echo "[run-chatbot-golden] refusing to run without RAKU_CHATBOT_SMOKE_APPROVED=yes" >&2
  exit 2
fi

out() {
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

if [ -z "${RAKU_PROD_BASE_URL:-}" ]; then
  ALB_DNS="$(out ApiLoadBalancerDnsName)"
  if [ -z "$ALB_DNS" ] || [ "$ALB_DNS" = "None" ]; then
    echo "[run-chatbot-golden] ERROR: could not read ApiLoadBalancerDnsName from $STACK." >&2
    exit 2
  fi
  export RAKU_PROD_BASE_URL="http://${ALB_DNS}/v1"
fi

DATASET="${CHATBOT_GOLDEN_DATASET:-$ROOT/scripts/demo/chatbot_golden_scenarios.json}"

echo "[run-chatbot-golden] stack=$STACK region=$REGION base=${RAKU_PROD_BASE_URL}"
echo "[run-chatbot-golden] dataset=$DATASET"
echo "[run-chatbot-golden] issuing Cognito smoke token"
export RAKU_PROD_BEARER_TOKEN="$(
  STACK="$STACK" AWS_REGION="$REGION" \
    RAKU_SMOKE_USERNAME="${RAKU_SMOKE_USERNAME:?set RAKU_SMOKE_USERNAME}" \
    RAKU_SMOKE_PASSWORD="${RAKU_SMOKE_PASSWORD:?set RAKU_SMOKE_PASSWORD}" \
    bash "$ROOT/scripts/aws/issue-smoke-token.sh"
)"

ARGS=(--dataset "$DATASET" --ensure-policy)
if [ -n "${CHATBOT_GOLDEN_OUTPUT:-}" ]; then
  ARGS+=(--output "$CHATBOT_GOLDEN_OUTPUT")
fi
if [ -n "${RAKU_CHATBOT_EVAL_PROFILE:-}" ]; then
  ARGS+=(--profile-name "$RAKU_CHATBOT_EVAL_PROFILE")
fi

bash "$ROOT/scripts/demo/chatbot_golden_scorecard.sh" "${ARGS[@]}" "$@"
