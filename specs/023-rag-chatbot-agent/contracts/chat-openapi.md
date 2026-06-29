# Contract: RAG-Connected ChatBot OpenAPI Surface

**Feature**: `023-rag-chatbot-agent`

**Date**: 2026-06-28

This contract defines the product-facing ChatBot API. Implementation routes through the existing NestJS facade and Python service composition. The ChatBot layer calls existing RAG answer/search contracts; it must not expose a separate knowledge path.

## Authentication and tenancy

- All public `/v1/chat/*` routes require signed auth context unless a tenant explicitly enables anonymous restricted chat.
- Tenant and user identity come from signed auth context, never from public request bodies.
- External/public chat uses signed public session or widget context plus domain allowlist; tenant IDs, source IDs, collection IDs, ACL tags, and exposure modes in public request bodies are ignored.
- Internal answer-service routes receive `x-raku-tenant-id`, `x-raku-user-id`, groups, roles, and correlation ID from the NestJS facade.
- RAG connector calls forward verified tenant/user claims to existing answer/search paths.

## Common response fields

All public `/v1/chat/*` 2xx responses MUST include the existing `api-version: 1` response header used by the NestJS facade. Chat response bodies MUST include `tenant_id` and `correlation_id`. They MAY include `api_version` as a client convenience alias, but the response header is authoritative for API versioning.

Typical Chat response body fields:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "correlation_id": "corr_..."
}
```

## Public API

### POST `/v1/chat/public-widget/sessions`

Restricted anonymous ChatBot entry uses a signed widget token, not the regular signed user token.
The route is intentionally separate from the authenticated session route so browser request bodies
cannot select tenant, channel, source, ACL scope, or collection scope.

Request:

```json
{
  "widget_token": "base64url(JSON).hmac",
  "initial_message": "料金を教えてください"
}
```

The server derives tenant, anonymous principal, `channel=public_widget`, allowed origin, and optional
collection scope from the signed widget token and request `Origin`. Body-supplied `tenant_id`,
`channel`, `source_id`, `collection_id`, ACL tags, exposure mode, and scenario filters are ignored.
Invalid tokens return 401, disallowed origins return 403, and widget rate limits return 429 before
the request reaches the internal answer-service.

### POST `/v1/chat/sessions`

Create a chat session.

Request:

```json
{
  "channel": "web_chat",
  "initial_message": "解約したいです",
  "metadata": {
    "language": "ja"
  }
}
```

Response `201`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "session_id": "chat_123",
  "status": "active",
  "processed_initial_message": false,
  "correlation_id": "corr_123"
}
```

If `initial_message` is provided, the first user message is stored and processed by the same orchestration path as `POST /messages`; the response includes the first assistant turn so the client does not need to submit the same message again:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "session_id": "chat_123",
  "status": "waiting_user",
  "processed_initial_message": true,
  "user_message_id": "msg_001",
  "assistant_message": {
    "message_id": "msg_002",
    "message": "承知しました。ご契約を確認するため、登録メールアドレスを教えてください。",
    "message_type": "text",
    "ai_action": "collect_slot",
    "quick_replies": [
      { "label": "人間に相談する", "value": "handoff" }
    ],
    "citations": []
  },
  "state": {
    "status": "waiting_user",
    "current_intent": "cancel_subscription",
    "current_step": "identify_customer",
    "collected_slots": {},
    "missing_slots": ["email", "company_name"]
  },
  "rag": null,
  "handoff": null,
  "ticket": null,
  "correlation_id": "corr_123"
}
```

### POST `/v1/chat/sessions/{session_id}/messages`

Submit the next user turn and receive the bot response. P0 is deterministic non-streaming. P1 may support `stream=true` using compatible event payloads.

P0 clients do not need WebSocket or SSE. The client should immediately render the user's message locally, show a bot typing/progress state while this HTTP request is pending, and reveal retry/handoff actions when the configured delay or timeout threshold is reached.

Request:

```json
{
  "message": "登録メールアドレスは user@example.com です",
  "client_message_id": "client_msg_001",
  "stream": false
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "session_id": "chat_123",
  "user_message_id": "msg_001",
  "assistant_message": {
    "message_id": "msg_002",
    "message": "ありがとうございます。次に会社名または契約者名を教えてください。",
    "message_type": "text",
    "ai_action": "collect_slot",
    "quick_replies": [
      { "label": "人間に相談する", "value": "handoff" }
    ],
    "citations": []
  },
  "state": {
    "status": "waiting_user",
    "response_state": "completed",
    "current_intent": "cancel_subscription",
    "current_step": "identify_customer",
    "collected_slots": {
      "email": "u***@example.com"
    },
    "missing_slots": ["company_name"]
  },
  "handoff": null,
  "ticket": null,
  "correlation_id": "corr_123"
}
```

Grounded answer response example:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "session_id": "chat_123",
  "user_message_id": "msg_010",
  "assistant_message": {
    "message_id": "msg_011",
    "message": "月途中の解約でも当月分は日割り返金されません。この内容で解約申請を進めますか？",
    "message_type": "text",
    "ai_action": "answer_with_citations",
    "quick_replies": [
      { "label": "進める", "value": "confirm" },
      { "label": "人間に相談する", "value": "handoff" }
    ],
    "citations": [
      {
        "source_id": "policy",
        "document_id": "DOC-CANCEL",
        "chunk_id": "chunk_456",
        "version": 7,
        "retrieval_score": 0.91,
        "title": "契約・解約ポリシー"
      }
    ]
  },
  "rag": {
    "rag_interaction_id": "rag_chat_001",
    "status": "ok",
    "answerable": true,
    "confidence": 0.88,
    "trace_id": "rag_trace_001",
    "latency_ms": 1230
  },
  "state": {
    "status": "waiting_user",
    "response_state": "completed",
    "current_step": "confirm_final",
    "missing_slots": []
  },
  "handoff": null,
  "ticket": null,
  "correlation_id": "corr_123"
}
```

### GET `/v1/chat/sessions/{session_id}`

Read a chat session detail.

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "session_id": "chat_123",
  "status": "resolved",
  "current_intent": "cancel_subscription",
  "scenario_version_id": "csv_7",
  "summary": "顧客は解約を希望し、解約ポリシーを確認後にチケット作成を承認。",
  "messages": [
    {
      "message_id": "msg_001",
      "role": "user",
      "content_redacted": "解約したいです"
    },
    {
      "message_id": "msg_011",
      "role": "assistant",
      "content_redacted": "月途中の解約でも当月分は日割り返金されません。この内容で解約申請を進めますか？",
      "citations": [
        {
          "document_id": "DOC-CANCEL",
          "chunk_id": "chunk_456",
          "version": 7,
          "retrieval_score": 0.91
        }
      ]
    }
  ],
  "state": {
    "collected_slots": {
      "email": "u***@example.com",
      "company_name": "ABC株式会社"
    },
    "missing_slots": []
  },
  "handoff": null,
  "ticket": {
    "ticket_id": "ticket_123",
    "status": "created"
  },
  "correlation_id": "corr_123"
}
```

### GET `/v1/chat/sessions`

Search chat sessions for admin/reviewer/operator views.

Query parameters:

```text
from
to
user_id
intent
status
handoff_reason
ticket_status
scenario_id
rating
limit
cursor
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "items": [
    {
      "session_id": "chat_123",
      "started_at": "2026-06-28T08:00:00Z",
      "last_message_at": "2026-06-28T08:04:00Z",
      "current_intent": "cancel_subscription",
      "status": "ticket_created",
      "resolution_status": "ticket_created",
      "handoff_required": false,
      "scenario_version_id": "csv_7"
    }
  ],
  "next_cursor": null,
  "correlation_id": "corr_list"
}
```

### POST `/v1/chat/sessions/{session_id}/handoff`

Explicitly request human handoff.

Request:

```json
{
  "reason": "customer_requested_human",
  "comment": "担当者に相談したい"
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "session_id": "chat_123",
  "handoff_package_id": "handoff_123",
  "status": "queued",
  "reason": "customer_requested_human",
  "correlation_id": "corr_handoff"
}
```

### GET `/v1/chat/handoffs/{handoff_package_id}`

Read handoff package.

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "handoff_package_id": "handoff_123",
  "session_id": "chat_123",
  "status": "queued",
  "reason": "insufficient_evidence",
  "priority": "normal",
  "summary": "顧客は特別割引の可否を質問。承認済み根拠が不足したため引き継ぎ。",
  "collected_slots": {
    "company_name": "ABC株式会社"
  },
  "missing_slots": [],
  "rag_citations": [],
  "recommended_action": "個別契約条件を確認してください。",
  "correlation_id": "corr_handoff"
}
```

### POST `/v1/chat/sessions/{session_id}/feedback`

Submit user or reviewer feedback.

Request:

```json
{
  "message_id": "msg_011",
  "rating": 2,
  "issue_type": "rag_gap",
  "comment": "返金条件の例外が説明されていません"
}
```

Response `201`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "evaluation_id": "eval_123",
  "improvement_item_id": "imp_123",
  "correlation_id": "corr_feedback"
}
```

### Scenario management APIs

P0 exposes backend scenario lifecycle APIs so deterministic scenarios can be seeded, reviewed, approved, published, previewed, and rolled back without a polished editor. P1 adds the full admin UI for these APIs.

```text
GET  /v1/chat/scenarios
POST /v1/chat/scenarios
PUT  /v1/chat/scenarios/{scenario_id}/versions/{version_id}
POST /v1/chat/scenarios/{scenario_id}/versions/{version_id}/preview
POST /v1/chat/scenarios/{scenario_id}/versions/{version_id}/submit-review
POST /v1/chat/scenarios/{scenario_id}/versions/{version_id}/approve
POST /v1/chat/scenarios/{scenario_id}/versions/{version_id}/publish
POST /v1/chat/scenarios/{scenario_id}/versions/{version_id}/schedule
POST /v1/chat/scenarios/{scenario_id}/versions/{version_id}/archive
POST /v1/chat/scenarios/{scenario_id}/rollback
```

Publication semantics match the phone feature: draft or in-review versions cannot be published unless explicitly approved first.

### GET `/v1/chat/metrics`

Read ChatBot dashboard metrics.

Query:

```text
from
to
bucket=hour|day|week
scenario_id
intent
channel
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "summary": {
    "conversation_count": 120,
    "bot_resolution_rate": 0.64,
    "handoff_rate": 0.23,
    "unanswered_rate": 0.08,
    "rag_answerable_rate": 0.79,
    "average_turns": 4.2,
    "p95_response_latency_ms": 2400
  },
  "top_intents": [
    { "key": "cancel_subscription", "count": 18 }
  ],
  "top_handoff_reasons": [
    { "key": "insufficient_evidence", "count": 9 }
  ],
  "correlation_id": "corr_metrics"
}
```

### Data lifecycle APIs

```text
POST /v1/chat/sessions/export
POST /v1/chat/sessions/{session_id}/delete-request
GET  /v1/chat/retention-policy
```

Export returns a redacted export job or audited `export_not_enabled`. Delete request queues redaction/deletion according to tenant policy.

### Data source ChatBot exposure APIs

Admins can decide which data sources or collections ChatBot may use. This policy is additional to existing RAG ACL; it never bypasses tenant isolation or document ACL.

P0 enforcement can apply collection-wide ChatBot exposure before calling the existing RAG answer
contract. Source-specific `source_id` policies remain draft/invalid with
`source_level_filter_requires_rag_adapter_support` until the RAG adapter accepts source-level
pre-retrieval filters.

```text
GET /v1/chat/source-exposure-policies
PUT /v1/chat/source-exposure-policies/{policy_id}
POST /v1/chat/source-exposure-policies/validate
```

Example `PUT` request:

```json
{
  "source_id": "public-faq",
  "collection_id": "default",
  "exposure_mode": "external_anonymous",
  "allowed_channels": ["public_widget"],
  "allowed_scenario_ids": ["cancel-basic", "pricing-faq"],
  "allowed_intents": ["cancel_subscription", "pricing_question"],
  "required_document_tags": ["public_chat"],
  "blocked_document_tags": ["internal_only", "secret", "credential"],
  "require_approved_effective": true,
  "allow_obsolete_primary_evidence": false,
  "allowed_domains": ["https://example.com"]
}
```

Example response:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "policy_id": "csep_public_faq",
  "source_id": "public-faq",
  "collection_id": "default",
  "exposure_mode": "external_anonymous",
  "status": "active",
  "correlation_id": "corr_source_exposure"
}
```

## Client Response States

These states are client-visible UI states for the P0 HTTP flow. They are not a separate transport protocol.

```text
sending             # user message has been accepted by the client and POST is in flight
thinking            # bot placeholder is visible while orchestrator starts
checking_rag        # optional label while existing RAG answer/search is running
checking_action     # optional label while ticket/handoff/action stub is checked
delayed             # configured delay threshold exceeded; show "still working" and handoff option
retryable_error     # timeout/network/server error; show retry and handoff option
handoff_available   # user can choose human handoff without waiting longer
completed           # assistant response, safe fallback, ticket, or handoff result is rendered
```

P0 server responses return the final state for the completed turn. Intermediate states are rendered by the client from request lifecycle and configured timeout thresholds. If future async job/polling is introduced for long-running turns, it must reuse these states.

## Existing RAG Connector Contract

The ChatBot layer calls existing RAG contracts rather than defining new knowledge contracts. P0 MUST adapt to the current shared DTOs:

- Answer request: `AnswerRequest` with `query` and optional `collection_id`.
- Search request: `SearchRequest` with `query`, optional `collection_id`, and optional `top_k`.
- Answer response: `AnswerResponse.status`, `text`, `citations`, `used_chunks`, `confidence`, `freshness`, and `correlation_id`.
- Search response: `SearchResponse.results` and `correlation_id`.

If the configured product answer route is safety-aware, such as the manufacturing-safe answer facade, ChatBot MUST use that configured route and must not bypass its high-risk, approval, obsolete/draft, provider policy, or ACL behavior.

Chat-specific request context is stored with the `RagInteraction` record and MAY be forwarded only after the shared DTO/OpenAPI contract is explicitly extended:

```json
{
  "query": "解約条件を確認したい",
  "collection_id": "default",
  "top_k": 5,
  "chat_context": {
    "session_id": "chat_123",
    "message_id": "msg_010",
    "conversation_summary_redacted": "ユーザーは解約を希望している",
    "intent": "cancel_subscription",
    "scenario_id": "cancel-basic",
    "scenario_version_id": "csv_7",
    "rag_filters_requested": {
      "category": ["contract", "cancel"],
      "customer_type": "business"
    },
    "server_derived_scope": {
      "allowed_source_ids": ["public-faq"],
      "exposure_policy_id": "csep_public_faq",
      "chat_mode": "external_anonymous"
    },
    "language": "ja"
  }
}
```

The NestJS facade/internal service must attach signed tenant and user claims. Public bodies cannot override those claims.

Effective ChatBot source scope is computed server-side:

```text
principal tenant/user/anonymous scope
  ∩ existing RAG ACL/tombstone/approval/provider policy
  ∩ ChatbotSourceExposurePolicy for the current source/collection
  ∩ scenario rag_policy filters
  ∩ channel/widget/domain restrictions
```

If the intersection is empty, ChatBot treats the turn as insufficient evidence or routes to handoff. It must not reveal that hidden sources exist.

Status mapping used by the ChatBot adapter:

| Existing RAG status | Derived chat answerable | Derived no-answer reason | Chat action |
|---|---:|---|---|
| `ok` with at least one valid citation for a knowledge claim | true | null | `answer_with_citations` or `confirm_action` |
| `insufficient_evidence` | false | `insufficient_evidence` | `ask_clarification` or `handoff` |
| `budget_exceeded` | false | `budget_exceeded` | `fallback` or `handoff` |
| `temporarily_unavailable` | false | `temporarily_unavailable` | `fallback` or `handoff` |

`risk_flags` are produced by ChatBot guardrails and, when present, by configured product-specific answer extensions. They are not required from the generic 001 `AnswerResponse`.

## Internal API Sketch

```text
POST /internal/chat/sessions
POST /internal/chat/sessions/{session_id}/messages
GET  /internal/chat/sessions
GET  /internal/chat/sessions/{session_id}
POST /internal/chat/sessions/{session_id}/handoff
GET  /internal/chat/handoffs/{handoff_package_id}
POST /internal/chat/sessions/{session_id}/feedback
GET  /internal/chat/metrics
POST /internal/chat/sessions/export
POST /internal/chat/sessions/{session_id}/delete-request
GET  /internal/chat/retention-policy
GET  /internal/chat/source-exposure-policies
PUT  /internal/chat/source-exposure-policies/{policy_id}
POST /internal/chat/source-exposure-policies/validate
GET  /internal/chat/scenarios
POST /internal/chat/scenarios
PUT  /internal/chat/scenarios/{scenario_id}/versions/{version_id}
POST /internal/chat/scenarios/{scenario_id}/versions/{version_id}/preview
POST /internal/chat/scenarios/{scenario_id}/versions/{version_id}/submit-review
POST /internal/chat/scenarios/{scenario_id}/versions/{version_id}/approve
POST /internal/chat/scenarios/{scenario_id}/versions/{version_id}/publish
POST /internal/chat/scenarios/{scenario_id}/versions/{version_id}/schedule
POST /internal/chat/scenarios/{scenario_id}/versions/{version_id}/archive
POST /internal/chat/scenarios/{scenario_id}/rollback
```

Internal routes must require the same internal auth mechanism as existing answer-service routes.

## Error Semantics

| Condition | Public HTTP | Body error code |
|---|---:|---|
| Missing auth | 401 | `unauthorized` |
| Anonymous chat disabled | 403 | `anonymous_chat_disabled` |
| Role not allowed | 403 | `forbidden` |
| Source not enabled for chat mode | 403 | `source_not_enabled_for_chatbot` |
| Session not found or not visible | 404 | `not_found` |
| Terminal session receives message | 409 | `session_terminal` |
| Duplicate client message/action | 409 | `duplicate_request` |
| Scenario version modified after publish | 409 | `scenario_version_immutable` |
| Scenario publish before approval | 409 | `scenario_version_not_approved` |
| Export disabled | 409 | `export_not_enabled` |
| RAG evidence insufficient | 200 | assistant action `ask_clarification` or `handoff` |
| RAG/provider temporarily unavailable | 200 | assistant action `fallback` or `handoff` |
| Unsafe request blocked | 200 | assistant action `handoff`, guardrail reason |
| Redaction failed | 500 | `redaction_failed` |

## Authorization Matrix

| Route group | Roles |
|---|---|
| Create/send own chat session | authenticated user, restricted anonymous when enabled |
| Read own session | session owner, `operator`, `ops_owner`, `tenant_admin` |
| Admin session search/detail | `ops_owner`, `tenant_admin`, `reviewer` |
| Read PII/raw-sensitive projection | `tenant_admin`, privileged audit role |
| Handoff package read | `operator`, `ops_owner`, `tenant_admin` |
| Scenario manage draft/preview | `tenant_admin`, `scenario_admin` |
| Scenario approve/publish/archive/rollback | `tenant_admin`, `scenario_approver` |
| Source exposure policy manage | `tenant_admin`, `scenario_admin`, privileged data admin |
| Feedback/review | session owner for user feedback; `reviewer`, `ops_owner`, `tenant_admin` for review |
| Metrics | `ops_owner`, `tenant_admin` |
| Export/deletion request | `tenant_admin`, privileged audit role |
