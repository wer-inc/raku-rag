# Migration Discipline

This project uses numbered SQL migrations under `infra/db/migrations/postgres/`.
The production runner records applied versions in `public.schema_migrations`; CI guards the
numbering and rollback shape with `tests/contract/test_migration_discipline.py`.

## Release Rules

1. Use contiguous `NNNN_name.sql` versions. Do not skip, reuse, or reorder numbers.
2. Every `NNNN_name.sql` must ship with `NNNN_name.down.sql`.
3. Prefer expand-first changes:
   - add nullable/defaulted columns first;
   - deploy code that can read old and new shapes;
   - backfill or migrate data;
   - only then contract/remove old fields in a later migration.
4. Avoid destructive down migrations for customer data. If rollback would lose data, use a
   documented forward-fix and make the down migration explicitly limited to schema cleanup.
5. A develop/customer release is not migration-green until Tier B has applied the complete numbered
   set on real Postgres and the multi-tenant release soak is green.

## Review Checklist

- Does the migration preserve tenant isolation and RLS for every tenant-owned table?
- Does the application remain compatible while old and new versions are briefly running together?
- Does the down pair exist and describe a safe operational rollback?
- Does `scripts/postgres-migration-smoke.sh` pick it up automatically?
