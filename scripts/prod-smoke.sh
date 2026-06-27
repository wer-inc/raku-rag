#!/usr/bin/env bash
set -euo pipefail

# Operator-run production smoke. This intentionally refuses to run unless a human has approved live
# production calls, because the answer path may invoke billed providers.
#
# Required:
#   RAKU_PROD_SMOKE_APPROVED=yes
#   RAKU_PROD_BASE_URL=https://example.com/v1
#   RAKU_PROD_BEARER_TOKEN=<Cognito JWT obtained through Hosted UI>
#   RAKU_SMOKE_COLLECTION_ID=<collection>
#   RAKU_SMOKE_GROUNDED_QUERY=<query expected to answer with citations>
#   RAKU_SMOKE_HIGH_RISK_QUERY=<query expected to be high-risk refused by manufacturing gate>
#   RAKU_SMOKE_POISON_QUERY=<query expected to refuse source-poisoned evidence>
#
# Optional but required for a no-skip promotion run:
#   RAKU_PROD_OTHER_BEARER_TOKEN=<Cognito JWT for a different tenant>
#   RAKU_SMOKE_ACL_QUERY=<query for cross-tenant probe>
#   RAKU_SMOKE_FORBIDDEN_DOCUMENT_ID=<document id that must never be cited>
#   RAKU_SMOKE_DELETED_QUERY=<query for a deleted/tombstoned document>
#   RAKU_SMOKE_DELETED_DOCUMENT_ID=<deleted document id that must never be cited>
#   RAKU_SMOKE_LANGFUSE_TRACE_CHECK_URL=<operator-provided trace lookup endpoint>
#   RAKU_SMOKE_DLQ_CHECK_URL=<operator-provided DLQ exercise/check endpoint>
#   RAKU_PROD_SMOKE_ALLOW_SKIPS=yes  # only for staging diagnostics, never for promotion evidence

if [[ "${RAKU_PROD_SMOKE_APPROVED:-}" != "yes" ]]; then
  echo "refusing to run live production smoke without RAKU_PROD_SMOKE_APPROVED=yes" >&2
  exit 2
fi

BASE_URL="${RAKU_PROD_BASE_URL:?set RAKU_PROD_BASE_URL, e.g. https://example.com/v1}"
TOKEN="${RAKU_PROD_BEARER_TOKEN:?set RAKU_PROD_BEARER_TOKEN to a Cognito JWT}"
COLLECTION_ID="${RAKU_SMOKE_COLLECTION_ID:?set RAKU_SMOKE_COLLECTION_ID}"
BASE_URL="${BASE_URL%/}"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

failures=0
skips=0

pass() { echo "PASS $*"; }
fail() {
  echo "FAIL $*" >&2
  failures=$((failures + 1))
}
skip() {
  echo "SKIP $*"
  skips=$((skips + 1))
}

dump_failure_response() {
  local name="$1" file="$2"
  if [[ "${RAKU_PROD_SMOKE_PRINT_RESPONSES:-}" == "yes" ]]; then
    echo "response for $name:" >&2
    python3 -m json.tool "$file" >&2 || cat "$file" >&2
    return
  fi
  echo "response summary for $name (set RAKU_PROD_SMOKE_PRINT_RESPONSES=yes to print full JSON):" >&2
  python3 - "$file" <<'PY' >&2
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)

summary = {}
for key in ("status", "reason", "trace_id", "correlation_id", "safety_block_reason"):
    if data.get(key) is not None:
        summary[key] = data.get(key)
manufacturing = data.get("manufacturing")
if isinstance(manufacturing, dict):
    summary["manufacturing"] = {
        key: manufacturing.get(key)
        for key in ("status", "high_risk", "safety_block_reason")
        if manufacturing.get(key) is not None
    }
citations = data.get("citations")
if isinstance(citations, list):
    summary["citations"] = [
        {
            key: citation.get(key)
            for key in ("document_id", "chunk_id", "source_id")
            if isinstance(citation, dict) and citation.get(key) is not None
        }
        for citation in citations[:5]
        if isinstance(citation, dict)
    ]
print(json.dumps(summary or {"keys": sorted(data.keys())}, ensure_ascii=False, indent=2))
PY
}

payload() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

query, collection_id = sys.argv[1], sys.argv[2]
body = {"query": query}
if collection_id:
    body["collection_id"] = collection_id
print(json.dumps(body))
PY
}

request_json() {
  local method="$1" path="$2" token="$3" body="$4" out="$5"
  local status
  local args=(-sS -o "$out" -w "%{http_code}" -X "$method" -H "content-type: application/json")
  if [[ -n "$token" ]]; then
    args+=(-H "authorization: Bearer $token")
  fi
  if [[ -n "$body" ]]; then
    args+=(--data "$body")
  fi
  status="$(curl "${args[@]}" "${BASE_URL}${path}")" || return 1
  [[ "$status" =~ ^2 ]]
}

check_json() {
  local name="$1" file="$2" expr="$3"
  if python3 - "$file" "$expr" <<'PY'
import json
import sys

path, expr = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
ok = bool(eval(expr, {"__builtins__": {}}, {"data": data, "len": len, "isinstance": isinstance}))
raise SystemExit(0 if ok else 1)
PY
  then
    pass "$name"
  else
    dump_failure_response "$name" "$file"
    fail "$name"
  fi
}

health="$tmpdir/health.json"
if request_json GET /health "" "" "$health"; then
  check_json "health" "$health" 'data.get("status") in ("ok", "healthy")'
else
  fail "health request"
fi

whoami="$tmpdir/whoami.json"
if request_json GET /whoami "$TOKEN" "" "$whoami"; then
  check_json "Cognito bearer auth" "$whoami" 'bool(data.get("principal", {}).get("tenant_id")) and bool(data.get("principal", {}).get("user_id"))'
else
  fail "Cognito bearer auth request"
fi

grounded_query="${RAKU_SMOKE_GROUNDED_QUERY:?set RAKU_SMOKE_GROUNDED_QUERY}"
grounded="$tmpdir/grounded.json"
if request_json POST /answer "$TOKEN" "$(payload "$grounded_query" "$COLLECTION_ID")" "$grounded"; then
  check_json "grounded answer has citations" "$grounded" 'data.get("status") == "ok" and bool(data.get("text")) and len(data.get("citations") or []) > 0'
else
  fail "grounded answer request"
fi

high_risk_query="${RAKU_SMOKE_HIGH_RISK_QUERY:?set RAKU_SMOKE_HIGH_RISK_QUERY}"
high_risk="$tmpdir/high-risk.json"
if request_json POST /manufacturing/answer "$TOKEN" "$(payload "$high_risk_query" "$COLLECTION_ID")" "$high_risk"; then
  check_json "high-risk refusal" "$high_risk" 'data.get("status") != "ok" and data.get("manufacturing", {}).get("high_risk") is True'
else
  fail "high-risk refusal request"
fi

poison_query="${RAKU_SMOKE_POISON_QUERY:?set RAKU_SMOKE_POISON_QUERY}"
poison="$tmpdir/source-poisoning.json"
if request_json POST /manufacturing/answer "$TOKEN" "$(payload "$poison_query" "$COLLECTION_ID")" "$poison"; then
  check_json "source poisoning refusal" "$poison" 'data.get("status") != "ok"'
else
  fail "source poisoning request"
fi

if [[ -n "${RAKU_PROD_OTHER_BEARER_TOKEN:-}" && -n "${RAKU_SMOKE_ACL_QUERY:-}" ]]; then
  acl="$tmpdir/acl.json"
  if request_json POST /answer "$RAKU_PROD_OTHER_BEARER_TOKEN" "$(payload "$RAKU_SMOKE_ACL_QUERY" "$COLLECTION_ID")" "$acl"; then
    if [[ -n "${RAKU_SMOKE_FORBIDDEN_DOCUMENT_ID:-}" ]]; then
      check_json "ACL cross-tenant probe" "$acl" 'all(c.get("document_id") != "'"${RAKU_SMOKE_FORBIDDEN_DOCUMENT_ID}"'" for c in (data.get("citations") or []))'
    else
      check_json "ACL cross-tenant probe" "$acl" 'data.get("status") != "ok"'
    fi
  else
    fail "ACL cross-tenant request"
  fi
else
  skip "ACL cross-tenant probe requires RAKU_PROD_OTHER_BEARER_TOKEN and RAKU_SMOKE_ACL_QUERY"
fi

if [[ -n "${RAKU_SMOKE_DELETED_QUERY:-}" ]]; then
  deleted="$tmpdir/deleted.json"
  if request_json POST /answer "$TOKEN" "$(payload "$RAKU_SMOKE_DELETED_QUERY" "$COLLECTION_ID")" "$deleted"; then
    if [[ -n "${RAKU_SMOKE_DELETED_DOCUMENT_ID:-}" ]]; then
      check_json "deletion/tombstone probe" "$deleted" 'all(c.get("document_id") != "'"${RAKU_SMOKE_DELETED_DOCUMENT_ID}"'" for c in (data.get("citations") or []))'
    else
      check_json "deletion/tombstone probe" "$deleted" 'data.get("status") != "ok"'
    fi
  else
    fail "deletion/tombstone request"
  fi
else
  skip "deletion/tombstone probe requires RAKU_SMOKE_DELETED_QUERY"
fi

if [[ -n "${RAKU_SMOKE_LANGFUSE_TRACE_CHECK_URL:-}" ]]; then
  trace="$tmpdir/langfuse.json"
  if curl -sS -o "$trace" "$RAKU_SMOKE_LANGFUSE_TRACE_CHECK_URL"; then
    check_json "Langfuse trace existence" "$trace" 'bool(data)'
  else
    fail "Langfuse trace check request"
  fi
else
  skip "Langfuse trace check requires RAKU_SMOKE_LANGFUSE_TRACE_CHECK_URL"
fi

if [[ -n "${RAKU_SMOKE_DLQ_CHECK_URL:-}" ]]; then
  dlq="$tmpdir/dlq.json"
  if curl -sS -o "$dlq" "$RAKU_SMOKE_DLQ_CHECK_URL"; then
    check_json "DLQ exercise" "$dlq" 'data.get("status") in ("ok", "exercised")'
  else
    fail "DLQ check request"
  fi
else
  skip "DLQ exercise requires RAKU_SMOKE_DLQ_CHECK_URL"
fi

if [[ "$skips" -gt 0 && "${RAKU_PROD_SMOKE_ALLOW_SKIPS:-}" != "yes" ]]; then
  fail "$skips smoke checks skipped; set the missing env vars or use RAKU_PROD_SMOKE_ALLOW_SKIPS=yes for diagnostics only"
fi

if [[ "$failures" -gt 0 ]]; then
  echo "production smoke FAILED: failures=$failures skips=$skips" >&2
  exit 1
fi

echo "production smoke GREEN: skips=$skips"
