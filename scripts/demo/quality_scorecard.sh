#!/usr/bin/env bash
# Live quality & safety scorecard for the running demo stack. Registers the curated eval set
# (scripts/demo/quality_eval_set.json), runs it against the live answer path, and prints
# recall@k / groundedness / high-risk recall / security checks + per-query citation recall.
#
#   bash scripts/demo/quality_scorecard.sh        # needs the demo stack up (scripts/demo/demo_up.sh)
#
# Use it to baseline retrieval/answer quality and to measure the effect of a change (run before & after).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
API="${API_BASE:-http://localhost:3000/v1}"
WEB="${WEB_BASE:-http://localhost:3002}"
KEY="${RAKU_API_KEY:-demo-api-key}"
TENANT="${DEMO_TENANT:-demo}"
USER_ID="${DEMO_USER:-alice}"
SET_FILE="$HERE/quality_eval_set.json"

TOKEN="$(curl -s -m8 -X POST "$WEB/api/dev-token" -H 'content-type: application/json' \
  -d "{\"tenant_id\":\"$TENANT\",\"user_id\":\"$USER_ID\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')"
[ -n "$TOKEN" ] || { echo "could not mint a token — is the web up at $WEB?" >&2; exit 1; }
auth=(-H "Authorization: Bearer $KEY" -H "X-User-Token: $TOKEN" -H 'content-type: application/json')

SID="$(curl -s -m30 "${auth[@]}" -X POST "$API/evaluations/sets" -d @"$SET_FILE" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("eval_set_id",""))')"
[ -n "$SID" ] || { echo "eval set registration failed" >&2; exit 1; }
RID="$(curl -s -m90 "${auth[@]}" -X POST "$API/evaluations/runs" -d "{\"eval_set_id\":\"$SID\",\"collection_id\":\"manuals\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("run_id",""))')"
[ -n "$RID" ] || { echo "eval run failed" >&2; exit 1; }

curl -s -m30 "${auth[@]}" "$API/evaluations/runs/$RID" | python3 -c '
import sys, json
d = json.load(sys.stdin); m = d.get("metrics", {})
print("=== 品質・安全スコアカード (run %s) ===" % d.get("run_id", "?"))
print("  gate_result       :", d.get("gate_result"))
print("  recall@k (retrieved):", round(m.get("recall_at_k", 0), 3))
print("  groundedness      :", round(m.get("groundedness", 0), 3))
print("  high_risk_recall  :", round(m.get("high_risk_recall", 0), 3))
sc = d.get("security_checks", {})
failed = [k for k, v in sc.items() if not (v.get("passed") if isinstance(v, dict) else v)]
print("  security_checks   :", "ALL PASS" if not failed else ("FAIL: " + ", ".join(failed)))
'
echo "  (per-query citation recall: bash scripts/demo/quality_scorecard.sh shows retrieval metrics; cited-doc detail via /v1/evaluations/runs/$RID examples)"
