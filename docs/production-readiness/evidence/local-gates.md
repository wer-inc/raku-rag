# Local And CI Gates Evidence

Status: pending

## Scope

- Requirement ID: PILOT-LOCAL-GATES
- Release commit:
- Environment:
- Operator:
- Date:

## Required Verification

```bash
git diff --check
scripts/gate.sh a
scripts/gate.sh all
npm run typecheck
npm run test:api
npm run build --workspace @raku-rag/web
python3 scripts/pilot_readiness_status.py
```

## CI Verification

- `gate.yml`:
- `ci.yml`:
- `security-scan.yml`:
- `deploy-checks.yml`:
- `deploy.yml` dry run:

## Results

- Outcome:
- Skips:
- Failures:

## Redaction Check

- [ ] No secrets
- [ ] No tokens
- [ ] No raw retrieved context
- [ ] No customer PII

