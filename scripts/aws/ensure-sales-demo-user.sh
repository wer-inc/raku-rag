#!/usr/bin/env bash
#
# Ensure the sales demo Cognito user has the tenant attribute and demo groups required by the
# production API JWT verifier. This is safe to re-run after deploys.
#
# Usage:
#   SALES_DEMO_PASSWORD='<password>' bash scripts/aws/ensure-sales-demo-user.sh
#
# Env:
#   STACK                         CloudFormation stack name (default: RakuRag-sales)
#   AWS_REGION                    AWS region (default: ap-northeast-1, or AWS_DEFAULT_REGION)
#   SALES_DEMO_EMAIL              Cognito username/email (default: sales-demo@example.com)
#   SALES_DEMO_NAME               Cognito display name (default: Sales Demo)
#   SALES_DEMO_TENANT_ID          Required custom tenant claim (default: demo)
#   SALES_DEMO_GROUPS             Space-separated Cognito groups
#                                 (default: "sales_demo reviewer tenant_admin")
#   SALES_DEMO_PASSWORD           Optional. When set, creates/resets the user's permanent password.
set -euo pipefail

STACK="${STACK:-RakuRag-sales}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-1}}"
EMAIL="${SALES_DEMO_EMAIL:-sales-demo@example.com}"
NAME="${SALES_DEMO_NAME:-Sales Demo}"
TENANT_ID="${SALES_DEMO_TENANT_ID:-demo}"
DEMO_GROUPS="${SALES_DEMO_GROUPS:-sales_demo reviewer tenant_admin}"
PASSWORD="${SALES_DEMO_PASSWORD:-}"
AWS=(aws --region "$REGION")

echo "[sales-demo-user] stack=$STACK region=$REGION email=$EMAIL tenant=$TENANT_ID"

out() {
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

POOL_ID="$(out CognitoUserPoolId)"
if [ -z "$POOL_ID" ] || [ "$POOL_ID" = "None" ]; then
  echo "[sales-demo-user] ERROR: could not read CognitoUserPoolId from $STACK." >&2
  exit 2
fi

ensure_group() {
  local group="$1"
  if "${AWS[@]}" cognito-idp get-group --user-pool-id "$POOL_ID" --group-name "$group" >/dev/null 2>&1; then
    return
  fi
  "${AWS[@]}" cognito-idp create-group --user-pool-id "$POOL_ID" --group-name "$group" >/dev/null
}

if "${AWS[@]}" cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username "$EMAIL" >/dev/null 2>&1; then
  echo "[sales-demo-user] updating existing user attributes"
  "${AWS[@]}" cognito-idp admin-update-user-attributes \
    --user-pool-id "$POOL_ID" \
    --username "$EMAIL" \
    --user-attributes \
      "Name=email,Value=$EMAIL" \
      "Name=email_verified,Value=true" \
      "Name=name,Value=$NAME" \
      "Name=custom:tenant_id,Value=$TENANT_ID"
else
  if [ -z "$PASSWORD" ]; then
    echo "[sales-demo-user] ERROR: user does not exist; set SALES_DEMO_PASSWORD to create it." >&2
    exit 2
  fi
  echo "[sales-demo-user] creating user"
  "${AWS[@]}" cognito-idp admin-create-user \
    --user-pool-id "$POOL_ID" \
    --username "$EMAIL" \
    --temporary-password "$PASSWORD" \
    --message-action SUPPRESS \
    --user-attributes \
      "Name=email,Value=$EMAIL" \
      "Name=email_verified,Value=true" \
      "Name=name,Value=$NAME" \
      "Name=custom:tenant_id,Value=$TENANT_ID" >/dev/null
fi

if [ -n "$PASSWORD" ]; then
  echo "[sales-demo-user] setting permanent password"
  "${AWS[@]}" cognito-idp admin-set-user-password \
    --user-pool-id "$POOL_ID" \
    --username "$EMAIL" \
    --password "$PASSWORD" \
    --permanent
fi

for group in $DEMO_GROUPS; do
  echo "[sales-demo-user] ensuring group=$group"
  ensure_group "$group"
  "${AWS[@]}" cognito-idp admin-add-user-to-group \
    --user-pool-id "$POOL_ID" \
    --username "$EMAIL" \
    --group-name "$group"
done

echo "[sales-demo-user] done"
