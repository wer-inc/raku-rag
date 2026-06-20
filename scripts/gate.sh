#!/usr/bin/env bash
#
# raku-rag loop-engineering gate — the single "No" the loop checks.
# See docs/loop-engineering.md.
#
# Usage:
#   scripts/gate.sh [a|b|all|separation]
#     a           Tier A hard gates only (zero-tolerance). DEFAULT. ~milliseconds, stdlib.
#     b           Tier B Postgres/pgvector/RLS bootstrap gate. Requires Docker/compose.
#     all         Full test suite (Tier A + integration + unit).
#     separation  Invariant check (§5): block gate/test edits mixed with src/ edits.
#
# Exit codes: 0 = green, 1 = test failure, 2 = unavailable/usage, 3 = separation violation.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="src"

MODE="${1:-a}"

banner() { printf '\n======== %s ========\n' "$1"; }

run_tier_a() {
  banner "Tier A — hard gates (zero tolerance)"
  # 001 security hard gates (top-level dir = repo root so `tests.helpers` imports resolve).
  python3 -m unittest discover -s tests/security -t . -p 'test_*.py' -q
  # 002 manufacturing hard gates — included automatically once they exist.
  if [ -d tests/manufacturing ]; then
    if ls tests/manufacturing/test_*gate*.py tests/manufacturing/test_*.py >/dev/null 2>&1; then
      python3 -m unittest discover -s tests/manufacturing -t . -p 'test_*.py' -q
    fi
  fi
  echo "Tier A: GREEN"
}

run_all() {
  banner "Full suite (Tier A + integration + unit)"
  python3 -m unittest discover -s tests -t . -p 'test_*.py' -q
  echo "Full suite: GREEN"
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required for Tier B but was not found on PATH." >&2
    echo "Run Tier B in a local/CI environment with Docker Compose available." >&2
    return 2
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose v2 is required for Tier B." >&2
    return 2
  fi
}

run_tier_b() {
  banner "Tier B — Postgres/pgvector/RLS bootstrap"
  require_docker
  local compose=(docker compose -f infra/docker-compose.yml)
  local gate_db="${POSTGRES_DB:-raku}_tier_b_gate"
  local user="${POSTGRES_USER:-raku}"
  local pass="${POSTGRES_PASSWORD:-raku}"

  "${compose[@]}" up -d postgres
  for _ in $(seq 1 30); do
    if "${compose[@]}" exec -T postgres pg_isready -U "$user" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  "${compose[@]}" exec -T postgres pg_isready -U "$user"
  "${compose[@]}" exec -T postgres dropdb -U "$user" --if-exists "$gate_db"
  "${compose[@]}" exec -T postgres createdb -U "$user" "$gate_db"

  run_rls_smoke() {
    "${compose[@]}" exec -T postgres psql -U "$user" -d "$gate_db" -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO tenants (tenant_id, name) VALUES ('tier_b_tenant_a', 'A')
  ON CONFLICT (tenant_id) DO UPDATE SET updated_at = now();
INSERT INTO tenants (tenant_id, name) VALUES ('tier_b_tenant_b', 'B')
  ON CONFLICT (tenant_id) DO UPDATE SET updated_at = now();
INSERT INTO collections (collection_id, tenant_id, name) VALUES ('tier_b_coll_a', 'tier_b_tenant_a', 'A')
  ON CONFLICT (collection_id) DO UPDATE SET updated_at = now();
INSERT INTO documents (document_id, tenant_id, collection_id, source_id, source_document_id, indexed_at)
  VALUES ('tier_b_doc_a', 'tier_b_tenant_a', 'tier_b_coll_a', 'tier_b_src', 'tier_b_src_doc', now())
  ON CONFLICT (document_id) DO UPDATE SET updated_at = now();
INSERT INTO chunks (chunk_id, tenant_id, document_id, collection_id, text, position)
  VALUES ('tier_b_chunk_a', 'tier_b_tenant_a', 'tier_b_doc_a', 'tier_b_coll_a', 'hello tier b', 0)
  ON CONFLICT (chunk_id) DO UPDATE SET updated_at = now();

SET ROLE raku_app;
SET app.current_tenant_id = 'tier_b_tenant_a';
SELECT 1 / CASE WHEN count(*) = 1 THEN 1 ELSE 0 END AS tenant_a_sees_own_doc
  FROM documents WHERE document_id = 'tier_b_doc_a';
SET app.current_tenant_id = 'tier_b_tenant_b';
SELECT 1 / CASE WHEN count(*) = 0 THEN 1 ELSE 0 END AS tenant_b_cannot_see_doc
  FROM documents WHERE document_id = 'tier_b_doc_a';
RESET ROLE;
SQL
  }

  "${compose[@]}" exec -T postgres psql -U "$user" -d "$gate_db" -v ON_ERROR_STOP=1 \
    < infra/db/migrations/postgres/0001_core_rls.sql
  run_rls_smoke
  "${compose[@]}" exec -T postgres psql -U "$user" -d "$gate_db" -v ON_ERROR_STOP=1 \
    < infra/db/migrations/postgres/0001_core_rls.down.sql
  "${compose[@]}" exec -T postgres psql -U "$user" -d "$gate_db" -v ON_ERROR_STOP=1 \
    < infra/db/migrations/postgres/0001_core_rls.sql
  run_rls_smoke

  # Python security parity: the SAME proven hard gates (ACL leak / tenant isolation incl.
  # last_prefiltered_count / deletion reappearance) against Postgres+RLS via the ProductionSystem.
  echo "--- Tier B security parity (Postgres-backed ProductionSystem) ---"
  RAKU_TEST_BACKEND=postgres POSTGRES_URL="postgresql://${user}:${pass}@localhost:5432/${gate_db}" \
    python3 -m unittest discover -s tests/security -t . -q
  echo "--- Tier B ranking/smoke parity (tests/postgres) ---"
  POSTGRES_URL="postgresql://${user}:${pass}@localhost:5432/${gate_db}" \
    python3 -m unittest discover -s tests/postgres -t . -q

  "${compose[@]}" exec -T postgres dropdb -U "$user" "$gate_db"

  python3 -m unittest tests.contract.test_tier_b_migration_sql -v
  echo "Tier B bootstrap: GREEN"
}

# Invariant 5: verification/generation separation.
# A single change must not edit a protected gate/test file AND src/ together
# (that is the "edit the test to make it pass" reward-hack smell).
run_separation() {
  banner "Separation invariant (§5)"
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "not a git repo — separation guard inactive"; return 0
  fi
  # The protected set = the 001 security gates, the 6 named 002 hard-gate test files, the unit gate
  # tests, and this gate script itself. (Not every test_*.py — only the hard gates; new feature tests
  # are free to land with their impl.)
  local protected='^(tests/security/|tests/contract/test_tier_b_.*\.py|infra/db/migrations/postgres/|tests/manufacturing/unit/|tests/manufacturing/test_(safety_gate|obsolete_draft_evidence|draft_only|acl_mapping|no_train|audit_coverage)\.py|scripts/gate\.sh$)'
  if ! git rev-parse HEAD >/dev/null 2>&1; then
    # No commits yet: nothing is "modified", invariant not yet enforceable.
    echo "no commits yet — separation guard inactive (becomes active after first commit)"; return 0
  fi
  # §5: flag only the reward-hack shape — MODIFYING an already-committed protected gate/test alongside
  # src/ (consistent with CI). Adding a NEW hard-gate test is allowed.
  local mod_protected src_changed
  mod_protected="$( { git diff --name-only --diff-filter=M HEAD; git diff --name-only --cached --diff-filter=M HEAD; } | sort -u | grep -E "$protected" || true)"
  src_changed="$( { git diff --name-only HEAD; git diff --name-only --cached; } | sort -u | grep -E '^src/' || true)"
  if [ -n "$mod_protected" ] && [ -n "$src_changed" ]; then
    echo "BLOCK: an existing hard-gate/test file was MODIFIED together with src/ — §5 separation violated." >&2
    echo "Gate changes must be a separate, independently-reviewed commit. Modified protected files:" >&2
    printf '%s\n' "$mod_protected" >&2
    return 3
  fi
  echo "separation OK"
}

case "$MODE" in
  a)          run_tier_a ;;
  b)          run_tier_b ;;
  all)        run_tier_a; run_all ;;
  separation) run_separation ;;
  *) echo "unknown mode: $MODE (use: a | b | all | separation)" >&2; exit 2 ;;
esac
