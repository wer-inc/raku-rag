#!/usr/bin/env bash
#
# Run scripts/prod-smoke.sh against a deployed CDK stack.
#
# The wrapper reads the public ALB URL and Cognito client id from CloudFormation outputs, obtains
# smoke JWTs through Cognito USER_PASSWORD_AUTH, then delegates all behavioral checks to
# scripts/prod-smoke.sh.
#
# Usage:
#   RAKU_PROD_SMOKE_APPROVED=yes \
#   RAKU_SMOKE_USERNAME='user@example.com' RAKU_SMOKE_PASSWORD='...' \
#   RAKU_SMOKE_COLLECTION_ID='manuals' \
#   RAKU_SMOKE_GROUNDED_QUERY='...' \
#   RAKU_SMOKE_HIGH_RISK_QUERY='...' \
#   RAKU_SMOKE_POISON_QUERY='...' \
#   STACK=RakuRag-sales AWS_REGION=ap-northeast-1 \
#   bash scripts/aws/run-prod-smoke-from-stack.sh
#
# Optional:
#   RAKU_SMOKE_OTHER_USERNAME / RAKU_SMOKE_OTHER_PASSWORD for the cross-tenant probe.
#   RAKU_PROD_BASE_URL to override the stack output-derived http://<ALB>/v1 base URL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STACK="${STACK:-RakuRag-sales}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-1}}"
AWS=(aws --region "$REGION")

if [[ "${RAKU_PROD_SMOKE_APPROVED:-}" != "yes" ]]; then
  echo "[run-prod-smoke] refusing to run without RAKU_PROD_SMOKE_APPROVED=yes" >&2
  exit 2
fi

out() {
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

if [ -z "${RAKU_PROD_BASE_URL:-}" ]; then
  # Prefer the CloudFront entry point when the stack has one: with httpsFront=cloudfront the ALB
  # listener is locked to CloudFront's origin-facing prefix list, so a direct http://<ALB> probe
  # times out by design.
  CF_URL="$(out HttpsFrontUrl || true)"
  if [ -n "$CF_URL" ] && [ "$CF_URL" != "None" ]; then
    export RAKU_PROD_BASE_URL="${CF_URL%/}/v1"
  else
    ALB_DNS="$(out ApiLoadBalancerDnsName)"
    if [ -z "$ALB_DNS" ] || [ "$ALB_DNS" = "None" ]; then
      echo "[run-prod-smoke] ERROR: could not read ApiLoadBalancerDnsName from $STACK." >&2
      exit 2
    fi
    export RAKU_PROD_BASE_URL="http://${ALB_DNS}/v1"
  fi
fi

echo "[run-prod-smoke] stack=$STACK region=$REGION base=${RAKU_PROD_BASE_URL}"
echo "[run-prod-smoke] issuing primary Cognito smoke token"
export RAKU_PROD_BEARER_TOKEN="$(
  STACK="$STACK" AWS_REGION="$REGION" \
    RAKU_SMOKE_USERNAME="${RAKU_SMOKE_USERNAME:?set RAKU_SMOKE_USERNAME}" \
    RAKU_SMOKE_PASSWORD="${RAKU_SMOKE_PASSWORD:?set RAKU_SMOKE_PASSWORD}" \
    bash "$ROOT/scripts/aws/issue-smoke-token.sh"
)"

if [ -n "${RAKU_SMOKE_OTHER_USERNAME:-}" ] || [ -n "${RAKU_SMOKE_OTHER_PASSWORD:-}" ]; then
  if [ -z "${RAKU_SMOKE_OTHER_USERNAME:-}" ] || [ -z "${RAKU_SMOKE_OTHER_PASSWORD:-}" ]; then
    echo "[run-prod-smoke] ERROR: set both RAKU_SMOKE_OTHER_USERNAME and RAKU_SMOKE_OTHER_PASSWORD." >&2
    exit 2
  fi
  echo "[run-prod-smoke] issuing cross-tenant Cognito smoke token"
  export RAKU_PROD_OTHER_BEARER_TOKEN="$(
    STACK="$STACK" AWS_REGION="$REGION" \
      RAKU_SMOKE_USERNAME="$RAKU_SMOKE_OTHER_USERNAME" \
      RAKU_SMOKE_PASSWORD="$RAKU_SMOKE_OTHER_PASSWORD" \
      bash "$ROOT/scripts/aws/issue-smoke-token.sh"
  )"
fi

bash "$ROOT/scripts/prod-smoke.sh"
