#!/usr/bin/env bash
#
# P3-1 — minimal forward/rollback Postgres migration runner.
#
# Tracks applied versions in a `schema_migrations` table so `up` is IDEMPOTENT (re-run = no-op) and
# `down` rolls back newest-first using the paired `*.down.sql`. The migration .sql files themselves use
# bare CREATE TABLE (not IF NOT EXISTS), so re-applying a file would error — the runner is what makes a
# clean apply-from-zero + idempotent re-apply + down round-trip mechanically verifiable. Complements the
# Docker-compose Tier-B bootstrap in scripts/gate.sh and the host smoke in postgres-migration-smoke.sh.
#
# Usage: POSTGRES_URL=<conn string> scripts/pg-migrate.sh up|down|status
# Exit: 0 ok; 2 usage/env error.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/infra/db/migrations/postgres"
URL="${POSTGRES_URL:-}"
if [ -z "$URL" ]; then
  echo "set POSTGRES_URL to a pgvector-enabled database." >&2
  exit 2
fi

psql_do() { psql "$URL" -v ON_ERROR_STOP=1 "$@"; }

ensure_table() {
  psql_do -q -c "CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
  );"
}

is_applied() {
  [ "$(psql_do -At -c "SELECT 1 FROM public.schema_migrations WHERE version='$1';")" = "1" ]
}

cmd="${1:-up}"
ensure_table

case "$cmd" in
  up)
    # extensions are idempotent (CREATE EXTENSION IF NOT EXISTS) — always safe to re-run.
    psql_do -q -f "$ROOT/infra/db/init/01-extensions.sql"
    for f in "$DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
      case "$f" in *.down.sql) continue ;; esac
      v="$(basename "$f" .sql)"
      if is_applied "$v"; then
        echo "skip  $v (already applied)"
        continue
      fi
      echo "apply $v"
      psql_do -q -f "$f"
      psql_do -q -c "INSERT INTO public.schema_migrations(version) VALUES ('$v') ON CONFLICT (version) DO NOTHING;"
    done
    echo "pg-migrate up: GREEN"
    ;;
  down)
    for v in $(psql_do -At -c "SELECT version FROM public.schema_migrations ORDER BY version DESC;"); do
      d="$DIR/$v.down.sql"
      if [ ! -f "$d" ]; then
        echo "no down migration for $v" >&2
        exit 1
      fi
      echo "revert $v"
      psql_do -q -f "$d"
      psql_do -q -c "DELETE FROM public.schema_migrations WHERE version='$v';"
    done
    echo "pg-migrate down: GREEN"
    ;;
  status)
    echo "applied migrations:"
    psql_do -At -c "SELECT version FROM public.schema_migrations ORDER BY version;"
    ;;
  *)
    echo "usage: POSTGRES_URL=... $0 up|down|status" >&2
    exit 2
    ;;
esac
