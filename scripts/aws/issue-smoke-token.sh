#!/usr/bin/env bash
#
# Issue a Cognito JWT for live smoke tests without printing credentials.
#
# Usage:
#   RAKU_SMOKE_USERNAME='user@example.com' RAKU_SMOKE_PASSWORD='...' \
#     STACK=RakuRag-sales AWS_REGION=ap-northeast-1 \
#     bash scripts/aws/issue-smoke-token.sh
#
# Env:
#   STACK                  CloudFormation stack name (default: RakuRag-sales)
#   AWS_REGION             AWS region (default: ap-northeast-1, or AWS_DEFAULT_REGION)
#   RAKU_SMOKE_USERNAME    Cognito username/email
#   RAKU_SMOKE_PASSWORD    Cognito password
#   RAKU_SMOKE_TOKEN_TYPE  id|access|refresh (default: id)
set -euo pipefail

STACK="${STACK:-RakuRag-sales}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-1}}"
USERNAME="${RAKU_SMOKE_USERNAME:?set RAKU_SMOKE_USERNAME}"
PASSWORD="${RAKU_SMOKE_PASSWORD:?set RAKU_SMOKE_PASSWORD}"
TOKEN_TYPE="${RAKU_SMOKE_TOKEN_TYPE:-id}"
AWS=(aws --region "$REGION")

case "$TOKEN_TYPE" in
  id) TOKEN_FIELD="IdToken" ;;
  access) TOKEN_FIELD="AccessToken" ;;
  refresh) TOKEN_FIELD="RefreshToken" ;;
  *)
    echo "[issue-smoke-token] ERROR: RAKU_SMOKE_TOKEN_TYPE must be id, access, or refresh." >&2
    exit 2
    ;;
esac

out() {
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

CLIENT_ID="$(out CognitoUserPoolClientId)"
if [ -z "$CLIENT_ID" ] || [ "$CLIENT_ID" = "None" ]; then
  echo "[issue-smoke-token] ERROR: could not read CognitoUserPoolClientId from $STACK." >&2
  exit 2
fi

CLI_INPUT="$(
  COGNITO_CLIENT_ID="$CLIENT_ID" RAKU_SMOKE_USERNAME="$USERNAME" RAKU_SMOKE_PASSWORD="$PASSWORD" python3 - <<'PY'
import json
import os

print(json.dumps({
    "AuthFlow": "USER_PASSWORD_AUTH",
    "ClientId": os.environ["COGNITO_CLIENT_ID"],
    "AuthParameters": {
        "USERNAME": os.environ["RAKU_SMOKE_USERNAME"],
        "PASSWORD": os.environ["RAKU_SMOKE_PASSWORD"],
    },
}))
PY
)"

TOKEN="$("${AWS[@]}" cognito-idp initiate-auth \
  --cli-input-json "$CLI_INPUT" \
  --query "AuthenticationResult.${TOKEN_FIELD}" \
  --output text)"

if [ -z "$TOKEN" ] || [ "$TOKEN" = "None" ]; then
  echo "[issue-smoke-token] ERROR: Cognito did not return ${TOKEN_FIELD}." >&2
  exit 1
fi

printf '%s\n' "$TOKEN"
