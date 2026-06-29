# Quickstart: AI Phone RAG Contact Center

**Feature**: `022-ai-phone-rag`

This quickstart describes the intended verification flow after implementation. It intentionally uses deterministic providers so the inner loop does not require live telephony, ASR, TTS, cloud, or billed calls.

Smoke S1 through S5 validate the P1 technical demo. Smoke S6 through S8 complete the product MVP acceptance slice from `goal.md`.

## 0. Preconditions

- Existing RAG core is available.
- Seeded tenant has FAQ/manual documents with ACL and current/approved metadata.
- Deterministic telephony, ASR, TTS, LLM, and handoff providers are selected.
- No production phone numbers or billed provider credentials are required.

## 1. Start local services

```bash
PYTHONPATH=src python3 apps/answer-service/server.py --seed --reset-demo-db --port 8088
ANSWER_SERVICE_URL=http://127.0.0.1:8088 API_PORT=3000 npm run start --workspace @raku-rag/api
npm run dev:web
```

If this feature lands behind a separate phone service command, replace the answer-service command with the phone-enabled composition root.

## 2. Seed phone scenario

Create a basic FAQ scenario:

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/scenarios \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "FAQ基本対応",
    "intent": "faq",
    "description": "承認済みFAQを根拠に回答し、根拠不足なら人間へ転送する",
    "owner_group": "support-admin"
  }'
```

Update, review, approve, and publish the scenario version:

```bash
curl -sS -X PUT http://127.0.0.1:3000/v1/phone/scenarios/faq-basic/versions/scv_1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "required_slots": [],
    "handoff_conditions": [
      {"reason": "customer_requested_human", "enabled": true},
      {"reason": "insufficient_evidence", "enabled": true}
    ],
    "fallback_message": "確認して担当者におつなぎします。"
  }'
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/scenarios/faq-basic/versions/scv_1/submit-review \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"comment":"MVP FAQ scenario review"}'
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/scenarios/faq-basic/versions/scv_1/approve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approval_comment":"MVP FAQ scenario approved"}'
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/scenarios/faq-basic/versions/scv_1/publish \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"publish_comment":"MVP FAQ scenario"}'
```

## 3. Smoke S1: Answerable FAQ call

Start simulated call:

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/calls/simulate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "caller": {"phone_number":"+81300000000","customer_id":"cust_demo"},
    "scenario_id":"faq-basic",
    "utterances":[{"type":"speech","text":"営業時間を教えてください"}],
    "options":{"recording_enabled":false}
  }'
```

Expected:

- response includes `call_id`
- first AI answer uses `answer_with_citations`
- citation includes `source_id`, `document_id`, `chunk_id`, `retrieval_score`
- call detail shows transcript and citation trace

## 4. Smoke S2: Insufficient evidence triggers handoff

Send an unsupported question:

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/calls/$CALL_ID/turns \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"speech","text":"この契約で返金を確約できますか？","asr_confidence":0.98}'
```

Expected:

- AI does not make a definitive refund promise
- `ai_action` is `handoff` or `ask_clarification` depending on scenario
- safety/evidence reason indicates insufficient evidence or high-risk boundary
- handoff package is created when handoff is selected

## 5. Smoke S3: Customer-requested human handoff

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/calls/$CALL_ID/turns \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"speech","text":"人につないでください","asr_confidence":0.99}'
```

Expected:

- `ai_action` is `handoff`
- `handoff.reason` is `customer_requested_human`
- AI response does not refuse the request
- `GET /v1/phone/handoffs/{id}` returns summary, transcript excerpt, confirmed slots, and destination

## 6. Smoke S4: Call history and traceability

```bash
curl -sS http://127.0.0.1:3000/v1/phone/calls/$CALL_ID \
  -H "Authorization: Bearer $TOKEN"
```

Expected:

- call detail includes:
  - `call_id`
  - `correlation_id`
  - `scenario_version_id`
  - redacted transcript
  - AI responses
  - citations
  - handoff package when applicable
  - recording URL only when recording was enabled and viewer has permission
- no raw secrets, tokens, card-like numbers, or internal auth headers are visible

## 7. Smoke S5: Scenario version trace

Update and publish a second scenario version, then run another call.

Expected:

- new calls record the new scenario version
- old calls still point to the old version
- published version content is immutable

## 8. Smoke S6: QA review creates improvement item

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/calls/$CALL_ID/quality-evaluations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "answer_correctness":3,
    "tone_score":4,
    "handoff_appropriateness":5,
    "compliance_issue":false,
    "hallucination_detected":true,
    "privacy_issue":false,
    "suggested_fix":"返金条件FAQを追加してください",
    "knowledge_gap_topics":["返金条件"]
  }'
```

Expected:

- QA evaluation is saved
- improvement item is created or linked
- audit entry records reviewer and call reference without raw private data

## 9. Smoke S7: Metrics dashboard

```bash
curl -sS "http://127.0.0.1:3000/v1/phone/metrics?bucket=day" \
  -H "Authorization: Bearer $TOKEN"
```

Expected:

- summary includes call count, AI containment, handoff rate, unresolved rate, p95 total turn latency
- top handoff reasons include `customer_requested_human` and/or `insufficient_evidence`
- knowledge gap topics include QA/handoff-derived gaps

## 10. Smoke S8: Retention, export, and deletion controls

```bash
curl -sS http://127.0.0.1:3000/v1/phone/retention-policy \
  -H "Authorization: Bearer $TOKEN"
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/calls/export \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"from":"2026-06-01T00:00:00Z","to":"2026-06-28T23:59:59Z","format":"csv","include_quality_evaluations":true}'
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/phone/calls/$CALL_ID/delete-request \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode":"redact","reason":"customer_privacy_request"}'
```

Expected:

- retention policy is visible to authorized roles
- export either queues a redacted export job or returns audited `export_not_enabled`
- deletion/redaction request is queued or denied with an audited retention-policy reason

## 11. Safety checks

Run the focused test set:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . -p 'test_phone_*.py' -q
npm run test:api
npm run typecheck --workspace @raku-rag/web
```

Then run the normal gates appropriate to touched areas:

```bash
scripts/gate.sh a
scripts/gate.sh all
```

## Expected product MVP demo story

1. Admin publishes an FAQ scenario.
2. Customer calls and asks a simple FAQ.
3. AI answers by voice with traceable evidence.
4. Customer asks for a human.
5. AI hands off with summary and reason.
6. Supervisor reviews the call and marks a knowledge gap.
7. Dashboard shows call count, AI containment, handoff reason, and knowledge gap.
8. Admin verifies retention/export/deletion controls.

This demonstrates the core principle: AI solves grounded, safe calls quickly and transfers calls it should not handle.
