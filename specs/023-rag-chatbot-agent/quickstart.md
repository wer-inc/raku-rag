# Quickstart: RAG-Connected Business ChatBot Agent

**Feature**: `023-rag-chatbot-agent`

This quickstart describes the intended deterministic P0 verification flow after implementation. It reuses the existing RAG answer/search stack and does not require live CRM, Slack, email, WebSocket, cloud, or billed providers.

## 0. Preconditions

- Existing RAG core is available.
- Seeded tenant has approved FAQ/policy documents and ACL metadata.
- Seeded tenant has at least one data source that can be explicitly enabled for ChatBot source exposure.
- Deterministic scenario, ticket, handoff, and notification providers are selected.
- No live business API credentials are required.

## 1. Start local services

```bash
PYTHONPATH=src python3 apps/answer-service/server.py --seed --reset-demo-db --port 8088
ANSWER_SERVICE_URL=http://127.0.0.1:8088 API_PORT=3000 npm run start --workspace @raku-rag/api
npm run dev:web
```

If ChatBot lands behind a separate composition root, replace the answer-service command with the chat-enabled service command.

## 2. Seed chat scenario

Create or seed a cancellation scenario. P0 requires these backend lifecycle APIs for deterministic setup and smoke tests; the polished scenario editor UI is P1.

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/scenarios \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "解約基本対応",
    "primary_intent": "cancel_subscription",
    "description": "必要情報を集め、解約ポリシーをRAGで確認し、最後にticket stubを作る",
    "owner_group": "support-admin"
  }'
```

Update, review, approve, and publish the scenario version:

```bash
curl -sS -X PUT http://127.0.0.1:3000/v1/chat/scenarios/cancel-basic/versions/csv_1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "steps": [
      {"id":"identify_customer","required_slots":["email","company_name"]},
      {"id":"explain_policy","use_rag":true,"rag_filters":{"category":["contract","cancel"]}},
      {"id":"confirm_final","required_slots":["final_confirmation"]},
      {"id":"create_ticket","action":"create_cancel_ticket"}
    ],
    "handoff_conditions": [
      {"reason":"customer_requested_human","enabled":true},
      {"reason":"insufficient_evidence","enabled":true},
      {"reason":"guardrail_blocked","enabled":true}
    ]
  }'
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/scenarios/cancel-basic/versions/csv_1/submit-review \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"comment":"P0 cancel scenario review"}'
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/scenarios/cancel-basic/versions/csv_1/approve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approval_comment":"P0 cancel scenario approved"}'
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/scenarios/cancel-basic/versions/csv_1/publish \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"publish_comment":"P0 cancel scenario"}'
```

## 3. Configure data source ChatBot exposure

Enable a seeded public FAQ/policy collection for this ChatBot scenario. This is an extra allowlist on top of existing RAG ACL. P0 uses collection-wide ChatBot exposure because the current RAG adapter cannot enforce source-level filters before retrieval.

```bash
curl -sS -X PUT http://127.0.0.1:3000/v1/chat/source-exposure-policies/csep_public_faq \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "",
    "collection_id": "default",
    "exposure_mode": "external_anonymous",
    "allowed_channels": ["web_chat", "public_widget"],
    "allowed_scenario_ids": ["cancel-basic"],
    "allowed_intents": ["cancel_subscription"],
    "required_document_tags": ["public_chat"],
    "blocked_document_tags": ["internal_only", "secret", "credential"],
    "require_approved_effective": true,
    "allow_obsolete_primary_evidence": false,
    "allowed_domains": ["https://example.com"]
  }'
```

Expected:

- policy is active for collection `default`
- policy does not grant access by itself; existing ACL and approval/effective checks still apply
- changing `exposure_mode` to `disabled` makes ChatBot treat that source as unavailable

## 4. Smoke S1: Create restricted public widget session

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/public-widget/sessions \
  -H "Origin: https://example.com" \
  -H "Content-Type: application/json" \
  -d '{"widget_token":"'$WIDGET_TOKEN'","initial_message":"料金を教えてください","tenant_id":"ignored","collection_id":"ignored"}'
```

Expected:

- no regular `Authorization` or `X-User-Token` is required
- tenant, `public_widget` channel, allowed domain, and collection scope come from the signed widget token
- request body attempts to override tenant/source/channel/collection/filter scope are ignored
- invalid token returns 401, disallowed domain returns 403, and widget rate limit returns 429

## 5. Smoke S2: Create authenticated session and collect first slot

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channel":"web_chat","initial_message":"解約したいです","metadata":{"language":"ja"}}'
```

Expected:

- UI renders the user's message immediately before the HTTP response returns
- UI shows bot typing/progress while the request is pending
- response includes `session_id`
- intent is or becomes `cancel_subscription`
- assistant asks for the first missing slot
- response includes the first `assistant_message` because `initial_message` is processed as the first turn
- no RAG call is required before scenario slot requirements

## 6. Smoke S3: Multi-turn slot filling

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/sessions/$SESSION_ID/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"user@example.com"}'
```

Expected:

- email is stored as masked/redacted slot display
- bot asks only for remaining slot
- state includes `missing_slots`

## 7. Smoke S4: Grounded RAG answer in scenario

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/sessions/$SESSION_ID/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"ABC株式会社です"}'
```

Expected:

- bot calls existing RAG answer/search path for cancel policy
- bot only uses sources enabled by source exposure policy for this chat mode
- response includes `answer_with_citations`
- citations include `source_id`, `document_id`, `chunk_id`, numeric `version` or document version, and `retrieval_score`
- state moves to final confirmation

## 8. Smoke S5: Ticket stub after final confirmation

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/sessions/$SESSION_ID/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"はい、進めてください","client_message_id":"confirm-001"}'
```

Expected:

- bot creates deterministic ticket stub
- response includes ticket ID or受付番号
- duplicate `client_message_id` does not create another ticket

## 9. Smoke S6: Insufficient evidence triggers handoff

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/sessions/$SESSION_ID/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"特別割引できますか？"}'
```

Expected:

- bot does not invent discount conditions
- action is `handoff`, `ask_clarification`, or safe fallback according to scenario
- handoff package exists if handoff is selected

## 10. Smoke S7: Human-requested handoff

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/sessions/$SESSION_ID/handoff \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"customer_requested_human","comment":"担当者に相談したい"}'
```

Expected:

- handoff reason is `customer_requested_human`
- handoff package contains summary, redacted transcript, slots, RAG citations, and recommended action

## 11. Smoke S8: Admin history and review

```bash
curl -sS http://127.0.0.1:3000/v1/chat/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN"
```

```bash
curl -sS -X POST http://127.0.0.1:3000/v1/chat/sessions/$SESSION_ID/feedback \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"rating":2,"issue_type":"rag_gap","comment":"返金条件の例外が不足"}'
```

Expected:

- session detail includes messages, state, slots, RAG trace IDs, citations, handoff/ticket status
- feedback links to RAG improvement flow when issue type is `rag_gap`
- no raw secrets or internal headers are visible

## 12. Smoke S9: Metrics and lifecycle

```bash
curl -sS "http://127.0.0.1:3000/v1/chat/metrics?bucket=day" \
  -H "Authorization: Bearer $TOKEN"
```

```bash
curl -sS http://127.0.0.1:3000/v1/chat/retention-policy \
  -H "Authorization: Bearer $TOKEN"
```

Expected:

- metrics include conversation count, bot resolution rate, handoff rate, unanswered rate, RAG answerable rate derived from existing RAG status, average turns, and p95 latency
- retention policy is visible to authorized roles

## 13. Smoke S10: P0 response UX without WebSocket

Simulate a slow RAG or delayed orchestrator response.

Expected:

- Web Chat UI never stays visually idle after send.
- The user message appears immediately.
- A bot typing/progress indicator appears while the HTTP request is pending.
- After the configured delay threshold, UI shows a "still working" state and a human handoff option.
- On timeout or network error, UI shows retry and handoff options without losing the user's message.
- No WebSocket or SSE connection is required for this smoke.

## 14. Smoke S11: Disabled data source is not used by ChatBot

Set the policy to disabled and ask a question whose only evidence is in that source.

Expected:

- ChatBot does not answer from the disabled source
- ChatBot returns insufficient evidence, clarification, safe fallback, or handoff
- response does not reveal that the hidden source exists
- generic RAG/admin access for authorized users remains governed by existing ACL and is not changed by this ChatBot exposure policy

## 15. Safety checks

Focused tests after implementation:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . -p 'test_chatbot_*.py' -q
npm run test:api
npm run typecheck --workspace @raku-rag/web
```

Then run gates appropriate to touched areas:

```bash
scripts/gate.sh a
scripts/gate.sh all
```

## Expected P0 demo story

1. Customer opens Web Chat and says they want to cancel.
2. Bot identifies the cancellation scenario.
3. Bot collects required slots over multiple turns.
4. Bot calls existing RAG for cancellation policy.
5. Bot shows grounded answer with citations and asks final confirmation.
6. Bot creates a deterministic ticket stub after confirmation.
7. Customer asks for a human or asks an unsupported question.
8. Bot hands off with summary, transcript, slots, and RAG trace.
9. Admin reviews session detail and marks a RAG gap.
10. Dashboard shows resolution, handoff, unanswered, and RAG metrics.
