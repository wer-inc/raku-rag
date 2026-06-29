# Contract: AI Phone RAG OpenAPI Surface

**Feature**: `022-ai-phone-rag`

**Date**: 2026-06-28

This contract is the product-facing API shape. Implementation should route through the existing NestJS facade and Python core rather than exposing internal Python services directly.

## Authentication and tenancy

- All public `/v1/phone/*` routes require signed auth context.
- Tenant and user identity come from signed auth context, never from request body overrides.
- Internal answer-service routes receive `x-raku-tenant-id`, `x-raku-user-id`, groups, roles, and correlation ID from the NestJS facade.

## Common response fields

All public 2xx responses include these top-level fields:

```json
{
  "api_version": "v1",
  "correlation_id": "corr_...",
  "tenant_id": "tenant_a"
}
```

## Public API

### POST `/v1/phone/calls/simulate`

Start a deterministic simulated inbound call. Used for MVP, tests, demos, and scenario previews.

Request:

```json
{
  "caller": {
    "phone_number": "+81********",
    "customer_id": "cust_123"
  },
  "channel": "simulator",
  "scenario_id": "billing-basic",
  "utterances": [
    { "type": "speech", "text": "営業時間を教えてください" }
  ],
  "options": {
    "recording_enabled": false,
    "force_asr_confidence": 0.98
  }
}
```

Response `202`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "call_id": "call_123",
  "status": "active",
  "status_url": "/v1/phone/calls/call_123",
  "correlation_id": "corr_123"
}
```

### POST `/v1/phone/calls/{call_id}/turns`

Send the next caller event into an active call. For real telephony this is called by provider adapter/internal service; for simulator it is public to authorized test users.

Request:

```json
{
  "event_type": "speech",
  "text": "人につないでください",
  "dtmf_digits": null,
  "asr_confidence": 0.99
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "call_id": "call_123",
  "turn_id": "turn_004",
  "call_state": "handoff_pending",
  "ai_action": "handoff",
  "ai_response_text": "担当者におつなぎします。ここまでの内容を引き継ぎます。",
  "tts_audio_ref": "deterministic://tts/turn_004",
  "citations": [],
  "handoff": {
    "handoff_package_id": "handoff_123",
    "reason": "customer_requested_human",
    "destination_type": "queue",
    "destination_id": "general-support"
  },
  "safety": {
    "answered_with_evidence": false,
    "blocked_reason": null
  },
  "correlation_id": "corr_123"
}
```

### GET `/v1/phone/calls`

List call history.

Query parameters:

```text
from
to
customer_id
phone_number
intent
state
handoff_reason
scenario_id
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
      "call_id": "call_123",
      "started_at": "2026-06-28T08:00:00Z",
      "ended_at": "2026-06-28T08:03:10Z",
      "caller_phone_number_masked": "+81******1234",
      "customer_id": "cust_123",
      "intent": "business_hours",
      "state": "completed",
      "resolution_status": "resolved",
      "handoff_required": false,
      "scenario_id": "faq-basic",
      "scenario_version_id": "scv_7"
    }
  ],
  "next_cursor": null,
  "correlation_id": "corr_list"
}
```

### GET `/v1/phone/calls/{call_id}`

Read call detail.

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "call_id": "call_123",
  "state": "completed",
  "summary": "営業時間に関する問い合わせ。承認済みFAQを参照して回答。",
  "transcript": [
    {
      "turn_id": "turn_001",
      "speaker": "caller",
      "redacted_text": "営業時間を教えてください",
      "asr_confidence": 0.98
    },
    {
      "turn_id": "turn_002",
      "speaker": "ai",
      "redacted_text": "本日の営業時間は9時から18時です。",
      "citations": [
        {
          "source_id": "faq",
          "document_id": "FAQ-HOURS",
          "chunk_id": "chunk_1",
          "version": "2026-06-01",
          "retrieval_score": 0.91
        }
      ]
    }
  ],
  "handoff": null,
  "scenario_version_id": "scv_7",
  "correlation_id": "corr_123"
}
```

### GET `/v1/phone/handoffs/{handoff_package_id}`

Read operator handoff package.

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "handoff_package_id": "handoff_123",
  "call_id": "call_123",
  "status": "queued",
  "reason": "insufficient_evidence",
  "priority": "normal",
  "destination_type": "queue",
  "destination_id": "billing-support",
  "customer": {
    "customer_id": "cust_123",
    "phone_number_masked": "+81******1234"
  },
  "summary": "顧客は返金可否を質問。該当する承認済み根拠が不足したため転送。",
  "confirmed_slots": {
    "order_id": "ord_987"
  },
  "citations": [],
  "sentiment": "frustrated",
  "recommended_next_action": "返金ポリシーを確認し、必要なら責任者へエスカレーションしてください。",
  "correlation_id": "corr_123"
}
```

### POST `/v1/phone/handoffs/{handoff_package_id}/accept`

Operator accepts a handoff.

Request:

```json
{
  "operator_id": "op_123",
  "queue_id": "billing-support"
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "handoff_package_id": "handoff_123",
  "status": "accepted",
  "accepted_at": "2026-06-28T08:05:00Z",
  "correlation_id": "corr_123"
}
```

### GET `/v1/phone/scenarios`

List scenarios.

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "items": [
    {
      "scenario_id": "faq-basic",
      "name": "FAQ基本対応",
      "intent": "faq",
      "status": "published",
      "active_version_id": "scv_7",
      "updated_at": "2026-06-28T08:00:00Z"
    }
  ],
  "correlation_id": "corr_scenarios"
}
```

### POST `/v1/phone/scenarios`

Create scenario draft.

Request:

```json
{
  "name": "請求問い合わせ",
  "intent": "billing",
  "description": "契約番号を確認して請求FAQと業務APIを参照する",
  "owner_group": "billing-admin"
}
```

Response `201`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "scenario_id": "billing-basic",
  "status": "draft",
  "active_version_id": null,
  "correlation_id": "corr_create"
}
```

### PUT `/v1/phone/scenarios/{scenario_id}/versions/{version_id}`

Update a draft version. Published versions are immutable.

Request:

```json
{
  "required_slots": [
    { "slot": "contract_id", "prompt": "ご契約番号を教えてください", "max_attempts": 2 }
  ],
  "handoff_conditions": [
    { "reason": "customer_requested_human", "enabled": true },
    { "reason": "insufficient_evidence", "enabled": true }
  ],
  "fallback_message": "確認して担当者におつなぎします。"
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "scenario_id": "billing-basic",
  "scenario_version_id": "scv_8",
  "status": "draft",
  "correlation_id": "corr_update"
}
```

### POST `/v1/phone/scenarios/{scenario_id}/versions/{version_id}/test`

Run scenario preview conversation.

Request:

```json
{
  "utterances": [
    "請求金額について知りたい",
    "契約番号はC-123です"
  ]
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "scenario_id": "billing-basic",
  "scenario_version_id": "scv_8",
  "turns": [
    {
      "ai_action": "ask_clarification",
      "ai_response_text": "ご契約番号を教えてください。",
      "citations": []
    }
  ],
  "would_handoff": false,
  "correlation_id": "corr_test"
}
```

### POST `/v1/phone/scenarios/{scenario_id}/versions/{version_id}/submit-review`

Submit a draft scenario version for reviewer approval.

Request:

```json
{
  "comment": "請求FAQ v3 に基づく基本対応としてレビュー依頼"
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "scenario_id": "billing-basic",
  "scenario_version_id": "scv_8",
  "status": "in_review",
  "correlation_id": "corr_submit_review"
}
```

### POST `/v1/phone/scenarios/{scenario_id}/versions/{version_id}/approve`

Approve a scenario version. Approval does not publish by itself unless the caller separately calls publish.

Request:

```json
{
  "approval_comment": "請求FAQ v3 に基づく基本対応として承認"
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "scenario_id": "billing-basic",
  "scenario_version_id": "scv_8",
  "status": "approved",
  "correlation_id": "corr_approve"
}
```

### POST `/v1/phone/scenarios/{scenario_id}/versions/{version_id}/publish`

Publish an approved scenario version immediately. Draft or in-review versions return `scenario_version_not_approved`.

Request:

```json
{
  "publish_comment": "MVP請求シナリオとして公開"
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "scenario_id": "billing-basic",
  "active_version_id": "scv_8",
  "status": "published",
  "correlation_id": "corr_publish"
}
```

### POST `/v1/phone/scenarios/{scenario_id}/versions/{version_id}/schedule`

Schedule an approved scenario version for future publication.

Request:

```json
{
  "publish_at": "2026-07-01T00:00:00Z",
  "schedule_comment": "月初改定に合わせて公開"
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "scenario_id": "billing-basic",
  "scenario_version_id": "scv_8",
  "status": "scheduled",
  "scheduled_publish_at": "2026-07-01T00:00:00Z",
  "correlation_id": "corr_schedule"
}
```

### POST `/v1/phone/scenarios/{scenario_id}/versions/{version_id}/archive`

Archive a scenario version that should no longer be selected for new calls.

Request:

```json
{
  "archive_comment": "旧料金プランの案内を停止"
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "scenario_id": "billing-basic",
  "scenario_version_id": "scv_8",
  "status": "archived",
  "correlation_id": "corr_archive"
}
```

### POST `/v1/phone/scenarios/{scenario_id}/rollback`

Roll back a scenario by publishing a previous approved/published version or creating a new version that references the rollback target.

Request:

```json
{
  "target_version_id": "scv_7",
  "rollback_comment": "公開後の転送条件に問題があったため戻す"
}
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "scenario_id": "billing-basic",
  "active_version_id": "scv_9",
  "rollback_target_version_id": "scv_7",
  "status": "published",
  "correlation_id": "corr_rollback"
}
```

### POST `/v1/phone/calls/{call_id}/quality-evaluations`

Create QA review.

Request:

```json
{
  "answer_correctness": 3,
  "tone_score": 4,
  "handoff_appropriateness": 5,
  "compliance_issue": false,
  "hallucination_detected": true,
  "privacy_issue": false,
  "suggested_fix": "FAQに例外条件を追加してください",
  "knowledge_gap_topics": ["返金条件"]
}
```

Response `201`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "evaluation_id": "eval_123",
  "call_id": "call_123",
  "review_status": "open",
  "improvement_item_id": "imp_123",
  "correlation_id": "corr_eval"
}
```

### GET `/v1/phone/metrics`

Read dashboard metrics.

Query:

```text
from
to
bucket=hour|day|week
scenario_id
intent
queue_id
```

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "summary": {
    "call_count": 120,
    "ai_containment_rate": 0.62,
    "handoff_rate": 0.31,
    "unresolved_rate": 0.07,
    "average_handle_time_seconds": 210,
    "p95_total_turn_latency_ms": 1800
  },
  "top_handoff_reasons": [
    { "key": "insufficient_evidence", "count": 18 },
    { "key": "customer_requested_human", "count": 12 }
  ],
  "knowledge_gap_topics": [
    { "key": "返金条件", "count": 7 }
  ],
  "correlation_id": "corr_metrics"
}
```

### POST `/v1/phone/calls/export`

Create a tenant-scoped redacted export job for call and QA data. If export is disabled by tenant policy, return `409 export_not_enabled` and audit the denied attempt.

Request:

```json
{
  "from": "2026-06-01T00:00:00Z",
  "to": "2026-06-28T23:59:59Z",
  "format": "csv",
  "include_quality_evaluations": true
}
```

Response `202`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "export_job_id": "export_123",
  "status": "queued",
  "correlation_id": "corr_export"
}
```

### POST `/v1/phone/calls/{call_id}/delete-request`

Request deletion or redaction of a call and derived artifacts according to tenant retention policy.

Request:

```json
{
  "mode": "redact",
  "reason": "customer_privacy_request"
}
```

Response `202`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "call_id": "call_123",
  "deletion_request_id": "del_123",
  "status": "queued",
  "correlation_id": "corr_delete"
}
```

### GET `/v1/phone/retention-policy`

Read tenant retention and recording policy for phone artifacts.

Response `200`:

```json
{
  "api_version": "v1",
  "tenant_id": "tenant_a",
  "recording_enabled_default": false,
  "transcript_retention_days": 365,
  "audio_retention_days": null,
  "export_retention_days": 30,
  "correlation_id": "corr_retention"
}
```

## Internal API Sketch

These are implementation details between NestJS facade and Python answer-service. They are not public API.

```text
POST /internal/phone/calls/simulate
POST /internal/phone/calls/{call_id}/turns
GET  /internal/phone/calls
GET  /internal/phone/calls/{call_id}
POST /internal/phone/scenarios
PUT  /internal/phone/scenarios/{scenario_id}/versions/{version_id}
POST /internal/phone/scenarios/{scenario_id}/versions/{version_id}/test
POST /internal/phone/scenarios/{scenario_id}/versions/{version_id}/submit-review
POST /internal/phone/scenarios/{scenario_id}/versions/{version_id}/approve
POST /internal/phone/scenarios/{scenario_id}/versions/{version_id}/publish
POST /internal/phone/scenarios/{scenario_id}/versions/{version_id}/schedule
POST /internal/phone/scenarios/{scenario_id}/versions/{version_id}/archive
POST /internal/phone/scenarios/{scenario_id}/rollback
GET  /internal/phone/handoffs/{handoff_package_id}
POST /internal/phone/handoffs/{handoff_package_id}/accept
POST /internal/phone/calls/{call_id}/quality-evaluations
GET  /internal/phone/metrics
POST /internal/phone/calls/export
POST /internal/phone/calls/{call_id}/delete-request
GET  /internal/phone/retention-policy
```

Internal routes must require the same internal auth mechanism as existing answer-service routes and must never trust tenant/user IDs from public request bodies.

## Error Semantics

| Condition | Public HTTP | Body error code |
|---|---:|---|
| Missing auth | 401 | `unauthorized` |
| Role not allowed | 403 | `forbidden` |
| Call not found or not visible | 404 | `not_found` |
| Terminal call receives turn | 409 | `call_terminal` |
| Published scenario modified | 409 | `scenario_version_immutable` |
| Scenario publish requested before approval | 409 | `scenario_version_not_approved` |
| Export disabled by tenant policy | 409 | `export_not_enabled` |
| Deletion/redaction blocked by retention policy | 409 | `retention_policy_denied` |
| Provider unavailable, fallback succeeded | 200 | response action `fallback` |
| Provider unavailable, no fallback possible | 503 | `provider_unavailable` |
| Evidence insufficient | 200 | response action `handoff` or `ask_clarification`, safety reason `insufficient_evidence` |
| PII redaction failed | 500 or 202 flagged | `redaction_failed` |

## Authorization Matrix

| Route group | Roles |
|---|---|
| Simulate calls | `tenant_admin`, `ops_owner`, `qa_reviewer` in non-production/demo profiles |
| Read own/operator handoff package | `operator`, `ops_owner`, `tenant_admin` |
| Read call history | `ops_owner`, `tenant_admin`, `qa_reviewer` |
| Read recordings/full transcript | `ops_owner`, `tenant_admin`, privileged audit role |
| Manage scenario drafts and submit review | `tenant_admin`, `scenario_admin` |
| Approve, publish, schedule, archive, or roll back scenarios | `tenant_admin`, `scenario_approver` |
| Create QA reviews | `qa_reviewer`, `ops_owner`, `tenant_admin` |
| Metrics | `ops_owner`, `tenant_admin` |
| Export redacted call/QA data | `ops_owner`, `tenant_admin`, privileged audit role |
| Request call deletion/redaction | `tenant_admin`, privileged audit role |
| Read retention policy | `ops_owner`, `tenant_admin`, privileged audit role |
