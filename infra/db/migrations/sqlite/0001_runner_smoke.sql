-- Framework smoke migration for the DB-agnostic runner (src/raku_rag/migrations/runner.py).
-- Used ONLY by the CI "migration runner smoke" to prove the runner applies + records + is idempotent
-- on stdlib sqlite with no external service. The PRODUCTION Postgres+pgvector+RLS migrations live in
-- infra/db/migrations/postgres/ and are exercised against a real Postgres in gate.yml (tier-b) and
-- scripts/postgres-migration-smoke.sh. This file is intentionally sqlite-compatible and trivial.
CREATE TABLE IF NOT EXISTS runner_smoke (
  id INTEGER PRIMARY KEY,
  note TEXT NOT NULL
);
