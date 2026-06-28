#!/usr/bin/env bash
#
# Host-Postgres smoke for RT2/RT3:
#   - applies pgvector init SQL
#   - applies every numbered Postgres migration in infra/db/migrations/postgres/
#   - verifies vector extension, tenant RLS, and the 0007 evaluation_runs columns
#   - applies down migrations
#
# This complements `scripts/gate.sh b`, which remains the Docker Compose-backed Tier B gate.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB="${POSTGRES_SMOKE_DB:-raku_rt_migration_$(date +%s)_$$}"
POSTGRES_OS_USER="${POSTGRES_OS_USER:-postgres}"

as_postgres() {
  runuser -u "$POSTGRES_OS_USER" -- "$@"
}

cleanup() {
  as_postgres dropdb --if-exists "$DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT

as_postgres createdb "$DB"

as_postgres psql -d "$DB" -v ON_ERROR_STOP=1 -f infra/db/init/01-extensions.sql
mapfile -t up_migrations < <(
  find infra/db/migrations/postgres -maxdepth 1 -type f \
    -name '[0-9][0-9][0-9][0-9]_*.sql' ! -name '*.down.sql' | sort
)

for migration in "${up_migrations[@]}"; do
  as_postgres psql -d "$DB" -v ON_ERROR_STOP=1 -f "$migration"
done

vector_version="$(as_postgres psql -d "$DB" -v ON_ERROR_STOP=1 -Atc \
  "SELECT extname || ':' || extversion FROM pg_extension WHERE extname = 'vector';")"
if [[ "$vector_version" != vector:* ]]; then
  echo "vector extension was not installed" >&2
  exit 1
fi

required_table_count="$(as_postgres psql -d "$DB" -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM information_schema.tables
   WHERE table_schema='public'
     AND table_name IN (
       'tenants','documents','chunks','embeddings',
	       'provider_policies','retrieval_profiles','logging_policies',
	       'industry_profiles','metadata_schemas','draft_artifacts',
	     'real_estate_properties','investment_funds','manufacturing_document_metadata',
       'data_source_oauth'
	     );")"
if [[ "$required_table_count" != "14" ]]; then
  echo "expected 14 required tables, found $required_table_count" >&2
  exit 1
fi

# 0007 (eval-run persistence) ALTERs evaluation_runs additively — verify the new columns landed.
eval_run_columns="$(as_postgres psql -d "$DB" -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM information_schema.columns
   WHERE table_name='evaluation_runs'
     AND column_name IN ('gate_result','baseline_comparison','probe_results','probes_executed');")"
if [[ "$eval_run_columns" != "4" ]]; then
  echo "expected 4 evaluation_runs columns from 0007, found $eval_run_columns" >&2
  exit 1
fi

datasource_pk_columns="$(as_postgres psql -d "$DB" -v ON_ERROR_STOP=1 -Atc \
  "SELECT string_agg(a.attname, ',' ORDER BY keys.ord)
   FROM pg_index i
   CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS keys(attnum, ord)
   JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = keys.attnum
   WHERE i.indrelid = 'data_sources'::regclass AND i.indisprimary;")"
if [[ "$datasource_pk_columns" != "tenant_id,source_id" ]]; then
  echo "expected data_sources primary key tenant_id,source_id; found $datasource_pk_columns" >&2
  exit 1
fi

source_sync_status_check="$(as_postgres psql -d "$DB" -v ON_ERROR_STOP=1 -Atc \
  "SELECT pg_get_constraintdef(oid)
   FROM pg_constraint
   WHERE conrelid='source_sync_states'::regclass
     AND conname='source_sync_states_status_check';")"
if [[ "$source_sync_status_check" != *"partially_succeeded"* ]]; then
  echo "expected source_sync_states status check to allow partially_succeeded" >&2
  exit 1
fi

as_postgres psql -d "$DB" -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO tenants (tenant_id, name) VALUES ('rt_tenant_a', 'A')
  ON CONFLICT (tenant_id) DO UPDATE SET updated_at = now();
INSERT INTO tenants (tenant_id, name) VALUES ('rt_tenant_b', 'B')
  ON CONFLICT (tenant_id) DO UPDATE SET updated_at = now();
INSERT INTO collections (collection_id, tenant_id, name) VALUES ('rt_coll_a', 'rt_tenant_a', 'A')
  ON CONFLICT (collection_id) DO UPDATE SET updated_at = now();
INSERT INTO documents (document_id, tenant_id, collection_id, source_id, source_document_id, indexed_at)
  VALUES ('rt_doc_a', 'rt_tenant_a', 'rt_coll_a', 'rt_src', 'rt_src_doc', now())
  ON CONFLICT (document_id) DO UPDATE SET updated_at = now();
INSERT INTO chunks (chunk_id, tenant_id, document_id, collection_id, text, position, embedding)
  VALUES (
    'rt_chunk_a',
    'rt_tenant_a',
    'rt_doc_a',
    'rt_coll_a',
    'hello rt',
    0,
    array_fill(0.0::real, ARRAY[256])::vector
  )
  ON CONFLICT (chunk_id) DO UPDATE SET updated_at = now();

SET ROLE raku_app;
SET app.current_tenant_id = 'rt_tenant_a';
SELECT 1 / CASE WHEN count(*) = 1 THEN 1 ELSE 0 END AS tenant_a_sees_own_doc
  FROM documents WHERE document_id = 'rt_doc_a';
SET app.current_tenant_id = 'rt_tenant_b';
SELECT 1 / CASE WHEN count(*) = 0 THEN 1 ELSE 0 END AS tenant_b_cannot_see_doc
  FROM documents WHERE document_id = 'rt_doc_a';
RESET ROLE;
SQL

for ((i=${#up_migrations[@]} - 1; i >= 0; i--)); do
  down="${up_migrations[$i]%.sql}.down.sql"
  if [[ ! -f "$down" ]]; then
    echo "missing down migration for ${up_migrations[$i]}" >&2
    exit 1
  fi
  as_postgres psql -d "$DB" -v ON_ERROR_STOP=1 -f "$down"
done

echo "Postgres migration + pgvector smoke GREEN (${vector_version})"
