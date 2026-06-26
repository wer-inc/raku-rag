# Production Readiness Evidence

This directory stores operator-created evidence for the paid-pilot and production gates.

Do not store secrets, tokens, raw retrieved context, customer PII, or unredacted customer documents in
evidence files.

## Required Files For Paid Pilot

The gate in `specs/prod-readiness/paid-pilot-gate.json` currently expects:

- `local-gates.md`
- `sme-safety-signoff.md`
- `provider-spend-approval.md`
- `pilot-scope-approval.md`

Each evidence file must contain a top-level status line:

```text
Status: verified
```

or, for human approvals:

```text
Status: signed
```

Use the templates in `docs/production-readiness/evidence/templates/`.

