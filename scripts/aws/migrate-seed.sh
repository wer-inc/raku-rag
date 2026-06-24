#!/usr/bin/env bash
#
# One-command post-deploy: apply Postgres schema migrations + seed the curated demo KB, by running the
# stack's MigrateSeedTask as an ECS RunTask INSIDE the VPC (Aurora is private-isolated and the
# answer-service is internal-only, so this can't run from your laptop directly).
#
# Run AFTER `cdk deploy`. It reads everything it needs from the CloudFormation stack outputs.
#
# Usage:
#   AWS_REGION=ap-northeast-1 STACK=RakuRag-sales bash scripts/aws/migrate-seed.sh
#
# Env:
#   STACK       CloudFormation stack name (default: RakuRag-sales). prod => RakuRag-prod.
#   AWS_REGION  region (default: ap-northeast-1, or your AWS CLI default).
#
# Exit: 0 if the task ran and exited 0; non-zero otherwise (prints the task's CloudWatch logs).
set -euo pipefail

STACK="${STACK:-RakuRag-sales}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-1}}"
AWS=(aws --region "$REGION")

echo "[migrate-seed] stack=$STACK region=$REGION"

out() {
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

CLUSTER="$(out EcsClusterName)"
TASKDEF="$(out MigrateSeedTaskDefinitionArn)"
SUBNETS="$(out PrivateSubnetIds)"
SG="$(out EcsTaskSecurityGroupId)"

if [ -z "$CLUSTER" ] || [ "$CLUSTER" = "None" ] || [ -z "$TASKDEF" ] || [ "$TASKDEF" = "None" ]; then
  echo "[migrate-seed] ERROR: could not read stack outputs. Is '$STACK' deployed in $REGION?" >&2
  exit 2
fi

echo "[migrate-seed] cluster=$CLUSTER"
echo "[migrate-seed] taskdef=$TASKDEF"
echo "[migrate-seed] launching one-off task in private subnets ($SUBNETS)…"

# Tasks run in PRIVATE_WITH_EGRESS subnets (egress to ECR/Aurora via NAT) — no public IP.
TASK_ARN="$("${AWS[@]}" ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASKDEF" \
  --launch-type FARGATE \
  --count 1 \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SG}],assignPublicIp=DISABLED}" \
  --query 'tasks[0].taskArn' --output text)"

if [ -z "$TASK_ARN" ] || [ "$TASK_ARN" = "None" ]; then
  echo "[migrate-seed] ERROR: run-task did not return a task ARN." >&2
  exit 1
fi
echo "[migrate-seed] task=$TASK_ARN — waiting for it to finish…"
"${AWS[@]}" ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN"

EXIT_CODE="$("${AWS[@]}" ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].containers[0].exitCode' --output text)"
REASON="$("${AWS[@]}" ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].stoppedReason' --output text)"

echo "[migrate-seed] container exitCode=$EXIT_CODE reason=$REASON"
echo "[migrate-seed] logs: CloudWatch log group /ecs (stream prefix migrate-seed) — or:"
echo "    ${AWS[*]} logs tail \$(aws --region $REGION logs describe-log-groups --query \"logGroups[?contains(logGroupName, 'MigrateSeed')].logGroupName\" --output text) --since 10m"

if [ "$EXIT_CODE" != "0" ]; then
  echo "[migrate-seed] FAILED — inspect the CloudWatch logs above." >&2
  exit 1
fi
echo "[migrate-seed] done: schema applied + demo KB seeded."
