#!/usr/bin/env bash
# Seed the PoC demo tenant with the curated 東洋精機 manufacturing knowledge base.
# Clean slate (removes prior demo docs) then ingest scripts/demo/demo_docs.json via the
# running answer-service. Requires: Postgres + answer-service up (see scripts/demo/demo_up.sh).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DSN="${POSTGRES_URL:-postgresql://raku:raku@127.0.0.1:5432/raku_demo}"
TENANT="${DEMO_TENANT:-demo}"

# NOTE: this script assumes the answer-service was started fresh with --reset-demo-db
# (see scripts/demo/demo_up.sh). Do NOT delete documents directly in Postgres here — the
# answer-service keeps an ingestion-dedup state that a raw DELETE desyncs, making a re-ingest
# of the same document_id a silent no-op (chunks=0). A full --reset-demo-db is the clean reset.

echo "[demo-seed] removing toy seed docs (m1/m2/m3) for a clean KB…"
PGPASSWORD="${PGPASSWORD:-raku}" psql "$DSN" -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<SQL || true
SET search_path TO public;
DELETE FROM chunks WHERE tenant_id='${TENANT}' AND document_id IN ('m1','m2','m3');
DELETE FROM manufacturing_document_metadata WHERE tenant_id='${TENANT}' AND document_id IN ('m1','m2','m3');
DELETE FROM documents WHERE tenant_id='${TENANT}' AND document_id IN ('m1','m2','m3');
SQL

echo "[demo-seed] ingesting curated knowledge base…"
ANSWER_SERVICE_URL="${ANSWER_SERVICE_URL:-http://127.0.0.1:8088}" python3 "$HERE/demo_seed.py"
