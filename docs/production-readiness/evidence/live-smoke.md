# Live Smoke Evidence

Status: pending

## Scope

- Requirement ID: PILOT-LIVE-SMOKE / P4-5
- Release commit:
- Environment:
- Operator:
- Date:

## Commands

```bash
RAKU_PROD_SMOKE_APPROVED=yes \
  RAKU_SMOKE_USERNAME='<redacted>' \
  RAKU_SMOKE_PASSWORD='<redacted>' \
  RAKU_SMOKE_COLLECTION_ID='<collection>' \
  RAKU_SMOKE_GROUNDED_QUERY='<synthetic smoke query>' \
  RAKU_SMOKE_HIGH_RISK_QUERY='<synthetic high-risk query>' \
  RAKU_SMOKE_POISON_QUERY='<synthetic source-poisoning query>' \
  STACK=RakuRag-sales \
  AWS_REGION=ap-northeast-1 \
  bash scripts/aws/run-prod-smoke-from-stack.sh
```

## Required Result

- `scripts/prod-smoke.sh` exits 0.
- `production smoke GREEN: skips=0` is recorded.
- Cross-tenant, deletion/tombstone, Langfuse trace, and DLQ checks are not skipped for promotion.

## Results

- Outcome:
- Skips:
- Failures:
- Relevant trace IDs:
- Relevant CloudWatch alarm names:

## Redaction Check

- [ ] No secrets
- [ ] No tokens
- [ ] No raw retrieved context
- [ ] No customer PII

