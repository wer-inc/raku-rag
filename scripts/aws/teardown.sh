#!/usr/bin/env bash
#
# Tear the raku-rag AWS footprint down to zero recurring cost.
#
# `cdk destroy` alone is NOT enough and does not even complete on its own:
#   - the document bucket is versioned with no autoDeleteObjects, so CloudFormation hits
#     DELETE_FAILED on a non-empty bucket (raku-rag-stack.ts: `versioned: true`, `removalPolicy`);
#   - CDK bootstrap assets (ECR images + the staging bucket) live in the CDKToolkit stack and keep
#     billing for storage — the Docling-enabled worker/answer images are ~2GB each, per deploy;
#   - the Amazon Connect instance, the hand-created provider API-key secrets, KMS keys in their
#     pending-deletion window, and CloudWatch log groups all outlive the app stack.
#
# MODES
#   list     (default) read-only inventory + estimated leftovers. Changes nothing.
#   destroy  empty the buckets, then delete the app stack.
#   residual clean what survives the app stack (secrets, log groups, ECR images, bootstrap).
#
# SAFETY
#   - Nothing destructive runs without RAKU_TEARDOWN_APPROVED=yes.
#   - `prod` additionally requires RAKU_TEARDOWN_ALLOW_PROD=yes: prod resources are RETAIN +
#     deletionProtection, so a prod teardown is a deliberate data-destroying act, not a cleanup.
#   - This script never deletes the Connect instance or phone numbers (out-of-stack, and releasing a
#     DID is irreversible — you lose the number). It only reports them.
#
# Usage:
#   AWS_REGION=ap-northeast-1 bash scripts/aws/teardown.sh list
#   AWS_REGION=ap-northeast-1 STAGE=stg RAKU_TEARDOWN_APPROVED=yes bash scripts/aws/teardown.sh destroy
#   AWS_REGION=ap-northeast-1 RAKU_TEARDOWN_APPROVED=yes bash scripts/aws/teardown.sh residual
set -euo pipefail

MODE="${1:-list}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-1}}"
STAGE="${STAGE:-}"
AWS=(aws --region "$REGION")
APPROVED="${RAKU_TEARDOWN_APPROVED:-no}"
ALLOW_PROD="${RAKU_TEARDOWN_ALLOW_PROD:-no}"
DROP_BOOTSTRAP="${RAKU_TEARDOWN_DROP_BOOTSTRAP:-no}"

say() { printf '\n== %s ==\n' "$1"; }
need_approval() {
  if [ "$APPROVED" != "yes" ]; then
    echo "REFUSING: set RAKU_TEARDOWN_APPROVED=yes to run '$MODE'. Re-run 'list' to preview." >&2
    exit 3
  fi
}

# Evaluate the guards BEFORE touching AWS, so a missing approval fails instantly and offline.
case "$MODE" in
  destroy)
    need_approval
    [ -n "$STAGE" ] || { echo "Set STAGE=sales|stg|prod." >&2; exit 2; }
    if [ "$STAGE" = "prod" ] && [ "$ALLOW_PROD" != "yes" ]; then
      echo "REFUSING: prod resources are RETAIN + deletionProtection. Destroying prod DESTROYS CUSTOMER" >&2
      echo "DATA and still leaves retained resources behind. Set RAKU_TEARDOWN_ALLOW_PROD=yes if that is" >&2
      echo "genuinely what you want, and take an RDS snapshot first." >&2
      exit 3
    fi
    ;;
  residual) need_approval ;;
  list) ;;
  *) echo "usage: $0 [list|destroy|residual]" >&2; exit 2 ;;
esac

ACCOUNT="$("${AWS[@]}" sts get-caller-identity --query Account --output text)"
echo "account=$ACCOUNT region=$REGION mode=$MODE"

# ---------------------------------------------------------------- inventory --
list_stacks() {
  "${AWS[@]}" cloudformation describe-stacks \
    --query "Stacks[?starts_with(StackName,'RakuRag-')].[StackName,StackStatus]" --output text 2>/dev/null || true
}

inventory() {
  say "app stacks"
  list_stacks | sed 's/^/  /' || echo "  (none)"

  say "S3 buckets (must be emptied before the stack can delete)"
  "${AWS[@]}" s3api list-buckets --query "Buckets[?contains(Name,'raku-rag')].Name" --output text 2>/dev/null |
    tr '\t' '\n' | while read -r b; do
      [ -z "$b" ] && continue
      n="$("${AWS[@]}" s3api list-object-versions --bucket "$b" \
        --query 'length(Versions[])' --output text 2>/dev/null || echo '?')"
      echo "  $b  (object versions: $n)"
    done

  say "CDK bootstrap assets — survive 'cdk destroy', keep billing for storage"
  "${AWS[@]}" ecr describe-repositories \
    --query "repositories[?contains(repositoryName,'cdk-')].repositoryName" --output text 2>/dev/null |
    tr '\t' '\n' | while read -r r; do
      [ -z "$r" ] && continue
      bytes="$("${AWS[@]}" ecr describe-images --repository-name "$r" \
        --query 'sum(imageDetails[].imageSizeInBytes)' --output text 2>/dev/null || echo 0)"
      cnt="$("${AWS[@]}" ecr describe-images --repository-name "$r" \
        --query 'length(imageDetails[])' --output text 2>/dev/null || echo 0)"
      echo "  ECR $r: $cnt images, $(( ${bytes%.*} / 1024 / 1024 )) MiB"
    done
  "${AWS[@]}" s3api list-buckets --query "Buckets[?contains(Name,'cdk-')].Name" --output text 2>/dev/null |
    tr '\t' '\n' | sed '/^$/d;s/^/  S3 (bootstrap staging) /'

  say "Secrets Manager — hand-created ones are NOT stack-owned and survive"
  "${AWS[@]}" secretsmanager list-secrets \
    --query "SecretList[?contains(Name,'raku')].[Name,DeletedDate]" --output text 2>/dev/null | sed 's/^/  /'

  say "KMS keys pending deletion (still billed until the window elapses)"
  "${AWS[@]}" kms list-keys --query 'Keys[].KeyId' --output text 2>/dev/null | tr '\t' '\n' |
    while read -r k; do
      [ -z "$k" ] && continue
      st="$("${AWS[@]}" kms describe-key --key-id "$k" \
        --query 'KeyMetadata.[KeyState,DeletionDate]' --output text 2>/dev/null || true)"
      case "$st" in *PendingDeletion*) echo "  $k  $st" ;; esac
    done

  say "Amazon Connect — OUT OF STACK. Phone numbers bill monthly until released."
  "${AWS[@]}" connect list-instances \
    --query 'InstanceSummaryList[].[Id,InstanceAlias]' --output text 2>/dev/null | sed 's/^/  /' ||
    echo "  (connect not reachable / none)"
  echo "  NOTE: releasing a claimed DID is irreversible — you cannot get the number back."

  say "RDS snapshots (manual snapshots survive cluster deletion)"
  "${AWS[@]}" rds describe-db-cluster-snapshots --snapshot-type manual \
    --query 'DBClusterSnapshots[].[DBClusterSnapshotIdentifier,SnapshotCreateTime]' --output text 2>/dev/null |
    sed 's/^/  /' || true

  say "CloudWatch log groups"
  "${AWS[@]}" logs describe-log-groups \
    --query "logGroups[?contains(logGroupName,'raku')||contains(logGroupName,'RakuRag')].[logGroupName,storedBytes]" \
    --output text 2>/dev/null | sed 's/^/  /' || true
}

# ------------------------------------------------------------------ helpers --
empty_bucket() { # empty_bucket <name> — removes ALL versions and delete markers
  local b="$1" batch
  echo "  emptying s3://$b (all versions + delete markers)…"
  while :; do
    batch="$("${AWS[@]}" s3api list-object-versions --bucket "$b" --max-keys 500 \
      --query '{Objects: [Versions,DeleteMarkers][][].{Key:Key,VersionId:VersionId}}' \
      --output json 2>/dev/null || echo '{"Objects":null}')"
    case "$batch" in *'"Objects": null'*|*'"Objects":null'*) break ;; esac
    printf '%s' "$batch" > /tmp/raku-teardown-batch.json
    "${AWS[@]}" s3api delete-objects --bucket "$b" --delete file:///tmp/raku-teardown-batch.json \
      --query 'length(Deleted[])' --output text >/dev/null 2>&1 || break
  done
  rm -f /tmp/raku-teardown-batch.json
  echo "  emptied s3://$b"
}

# ------------------------------------------------------------------ destroy --
destroy_stack() { # guards already evaluated in the dispatch above
  local stack="RakuRag-${STAGE}"

  say "pre-flight: $stack"
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$stack" \
    --query 'Stacks[0].StackStatus' --output text

  say "emptying stack-owned buckets"
  "${AWS[@]}" s3api list-buckets \
    --query "Buckets[?contains(Name,'raku-rag-${STAGE}-')].Name" --output text 2>/dev/null |
    tr '\t' '\n' | while read -r b; do [ -n "$b" ] && empty_bucket "$b"; done

  say "deleting $stack (this removes NAT/ALB/Fargate/Aurora — the bulk of the bill)"
  "${AWS[@]}" cloudformation delete-stack --stack-name "$stack"
  echo "waiting for delete to complete (Aurora + CloudFront can take 15-30 min)…"
  if "${AWS[@]}" cloudformation wait stack-delete-complete --stack-name "$stack"; then
    echo "$stack deleted."
  else
    echo "DELETE did not complete. Inspect the failed resources:" >&2
    "${AWS[@]}" cloudformation describe-stack-events --stack-name "$stack" \
      --query "StackEvents[?ResourceStatus=='DELETE_FAILED'].[LogicalResourceId,ResourceStatusReason]" \
      --output text >&2 || true
    exit 1
  fi
  echo "NEXT: run '$0 residual' — the stack is gone but bootstrap/ECR/secrets still bill."
}

# ----------------------------------------------------------------- residual --
residual() { # guards already evaluated in the dispatch above
  say "force-deleting raku secrets (no recovery window = billing stops now)"
  "${AWS[@]}" secretsmanager list-secrets \
    --query "SecretList[?contains(Name,'raku')].Name" --output text 2>/dev/null | tr '\t' '\n' |
    while read -r s; do
      [ -z "$s" ] && continue
      echo "  deleting secret $s"
      "${AWS[@]}" secretsmanager delete-secret --secret-id "$s" \
        --force-delete-without-recovery >/dev/null 2>&1 || echo "    (skip: $s)"
    done

  say "deleting raku CloudWatch log groups"
  "${AWS[@]}" logs describe-log-groups \
    --query "logGroups[?contains(logGroupName,'raku')||contains(logGroupName,'RakuRag')].logGroupName" \
    --output text 2>/dev/null | tr '\t' '\n' |
    while read -r g; do
      [ -z "$g" ] && continue
      "${AWS[@]}" logs delete-log-group --log-group-name "$g" >/dev/null 2>&1 &&
        echo "  deleted $g" || echo "  (skip: $g)"
    done

  say "purging CDK asset images from ECR (biggest storage leftover: Docling images ~2GB each)"
  "${AWS[@]}" ecr describe-repositories \
    --query "repositories[?contains(repositoryName,'cdk-')].repositoryName" --output text 2>/dev/null |
    tr '\t' '\n' | while read -r r; do
      [ -z "$r" ] && continue
      ids="$("${AWS[@]}" ecr list-images --repository-name "$r" --query 'imageIds[*]' --output json 2>/dev/null || echo '[]')"
      [ "$ids" = "[]" ] && { echo "  $r already empty"; continue; }
      printf '%s' "$ids" > /tmp/raku-teardown-images.json
      "${AWS[@]}" ecr batch-delete-image --repository-name "$r" \
        --image-ids file:///tmp/raku-teardown-images.json --query 'length(imageIds[])' --output text >/dev/null 2>&1 &&
        echo "  purged images in $r" || echo "  (skip: $r)"
      rm -f /tmp/raku-teardown-images.json
    done

  if [ "$DROP_BOOTSTRAP" = "yes" ]; then
    say "deleting the CDK bootstrap stack (CDKToolkit) — a future deploy must re-bootstrap"
    "${AWS[@]}" s3api list-buckets --query "Buckets[?contains(Name,'cdk-')].Name" --output text 2>/dev/null |
      tr '\t' '\n' | while read -r b; do [ -n "$b" ] && empty_bucket "$b"; done
    "${AWS[@]}" cloudformation delete-stack --stack-name CDKToolkit &&
      echo "  CDKToolkit deletion requested."
  else
    say "keeping the CDK bootstrap (set RAKU_TEARDOWN_DROP_BOOTSTRAP=yes to remove it)"
    echo "  Empty bootstrap buckets/repos cost ~nothing; keeping them makes a future redeploy 1 command."
  fi

  say "STILL BILLING — manual, deliberate steps only you should take"
  echo "  1. Amazon Connect instance + claimed phone numbers (monthly per DID). Releasing a number"
  echo "     is IRREVERSIBLE. Console: Connect > instance > Phone numbers > release, then delete the instance."
  echo "  2. KMS keys are in a 7-30 day pending-deletion window and bill (~\$1/key/mo) until it elapses."
  echo "     They cannot be deleted faster; verify with: aws kms describe-key --key-id <id>"
  echo "  3. Manual RDS snapshots, if you took one before teardown (storage-billed)."
  echo "  4. Route53 hosted zones (~\$0.50/mo each) if you created one for a custom domain."
  echo "  5. Bedrock guardrail / model access: no standing charge, but delete the guardrail if unused."
  echo
  echo "  Verify the bill actually reaches zero (data lags ~24h):"
  echo "    aws ce get-cost-and-usage --time-period Start=\$(date -d '2 days ago' +%F),End=\$(date +%F) \\"
  echo "      --granularity DAILY --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE"
}

case "$MODE" in
  list) inventory ;;
  destroy) destroy_stack ;;
  residual) residual ;;
  *) echo "usage: $0 [list|destroy|residual]" >&2; exit 2 ;;
esac
