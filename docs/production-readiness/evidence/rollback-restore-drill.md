# Rollback And Restore Drill Evidence

Status: pending

## Scope

- Requirement ID: PILOT-ROLLBACK-RESTORE / P4-6
- Release commit:
- Environment:
- Witness:
- Date:

## Required Verification

- Application rollback to a previous known-good image digest.
- `/v1/health` passes after rollback.
- Grounded answer returns citations after rollback.
- Cross-tenant probe returns no leaked content after rollback.
- RDS snapshot restore to a scratch instance completes.
- Known answer and RLS probe pass on the restored database.
- Vector / lexical index rebuild and `ANALYZE` complete when required.

## Results

- Outcome:
- Rollback duration:
- Restore duration:
- Reindex duration:
- Relevant CloudWatch alarm names:
- Incident / change ticket:

## Signature

- Name:
- Role:
- Timestamp:

