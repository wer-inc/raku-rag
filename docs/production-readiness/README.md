# Production Readiness Docs

Start here when preparing a customer pilot or production promotion.

## Paid Pilot

- `paid-pilot-readiness.md` defines the CTO gate for a scoped paid pilot.
- `customer-trust-pack.md` is the customer-facing security and operations summary.
- `pilot-demo-script.md` is the fixed sales-engineering demo flow.
- `evidence/` contains evidence templates and operator-created proof.

Check current status:

```bash
python3 scripts/pilot_readiness_status.py
```

## Production Promotion

- `rag-production-readiness.md` is the deeper production-readiness audit.
- `release-execution-checklist.md` is the operator runbook.
- `release-and-rollback.md` and `vector-dr-runbook.md` cover rollback and recovery.
- `risk-register.md` tracks production-boundary risks.

