# Data Model: AI Phone RAG Contact Center

**Feature**: `022-ai-phone-rag`

**Date**: 2026-06-28

## Overview

This feature adds phone-specific entities while reusing existing raku-rag knowledge entities:

- Existing knowledge path: `Document`, `Chunk`, ACL, citations, approvals, source sync, deletion, evaluation.
- New phone path: call sessions, turns, scenarios, handoff packages, QA reviews, call metrics, provider configs.

Every new entity is tenant-scoped and must carry audit/trace identifiers.

## Entity: CallSession

Represents one inbound or simulated phone call.

### Fields

```text
tenant_id: string
call_id: string
correlation_id: string
channel: "phone" | "simulator" | "web_voice" | string
provider: string
provider_call_id: string | null

caller_phone_number: string | null     # masked in normal UI/log views
customer_id: string | null
customer_display_name: string | null

started_at: datetime
answered_at: datetime | null
ended_at: datetime | null
duration_seconds: number | null
state: "ringing" | "active" | "on_hold" | "handoff_pending" | "transferred" | "completed" | "abandoned" | "failed"

intent: string | null
intent_confidence: number | null
scenario_id: string | null
scenario_version_id: string | null
scenario_path: list[string]

summary: string | null
resolution_status: "resolved" | "unresolved" | "transferred" | "abandoned" | "callback_requested" | "failed" | null
disposition: string | null
csat_score: number | null

handoff_required: boolean
handoff_reason: string | null
handoff_destination: string | null
handoff_package_id: string | null

recording_enabled: boolean
recording_disclosure_played: boolean
audio_object_ref: string | null
transcript_redaction_status: "not_needed" | "redacted" | "flagged" | "failed"

retention_policy_ref: string | null
no_train_policy_ref: string | null
created_at: datetime
updated_at: datetime
```

### Invariants

- `tenant_id + call_id` is unique.
- `correlation_id` is required and propagates to all turns, provider calls, handoff, audit, and metrics.
- `caller_phone_number` must be masked in logs and normal UI unless viewer has an approved role.
- `scenario_version_id` is immutable once a turn has been processed under that scenario version.
- `state=completed/transferred/abandoned/failed` is terminal for call processing.

## Entity: ConversationTurn

Represents one caller/AI/system event in a call.

### Fields

```text
tenant_id: string
call_id: string
turn_id: string
sequence_no: number
speaker: "caller" | "ai" | "system" | "operator"
event_type: "speech" | "dtmf" | "barge_in" | "hold" | "resume" | "handoff" | "tool" | "error"

asr_text: string | null
asr_confidence: number | null
dtmf_digits: string | null
normalized_text: string | null
redacted_text: string | null

ai_action: "ask_clarification" | "answer_with_citations" | "handoff" | "fallback" | "end_call" | null
ai_response_text: string | null
tts_audio_ref: string | null

intent: string | null
sentiment: "neutral" | "frustrated" | "angry" | "anxious" | "unknown" | null
required_slots_before: map
required_slots_after: map

citations: list[PhoneCitationRef]
tool_calls: list[ToolCallRef]
safety_decision: map | null
handoff_reason: string | null

latency_ms: map               # asr, retrieval, generation, tts, total
created_at: datetime
```

### Invariants

- `sequence_no` is monotonic per call.
- AI turns with `answer_with_citations` must carry at least one valid citation unless the response is purely procedural (e.g., greeting, clarification, transfer notice).
- Raw/unredacted text is restricted; `redacted_text` is the default display/export field.

## Value Object: PhoneCitationRef

Traceable evidence used in a phone turn.

```text
source_id: string
document_id: string
chunk_id: string
version: string | null
retrieval_score: number
approval_status: string | null
effective_date: string | null
snippet_redacted: string | null
```

## Entity: CallScenario

Logical scenario edited by admins.

### Fields

```text
tenant_id: string
scenario_id: string
name: string
description: string | null
intent: string
status: "draft" | "in_review" | "approved" | "scheduled" | "published" | "archived"
active_version_id: string | null
owner_group: string | null
created_by: string
created_at: datetime
updated_at: datetime
```

### Invariants

- Only one active published version per `scenario_id`.
- Publishing requires a `ScenarioVersion` in approved state.

## Entity: ScenarioVersion

Immutable version of a scenario.

### Fields

```text
tenant_id: string
scenario_id: string
scenario_version_id: string
version_number: number
status: "draft" | "in_review" | "approved" | "scheduled" | "published" | "archived"

entry_conditions: list[Condition]
steps: list[ScenarioStep]
required_slots: list[RequiredSlot]
branch_conditions: list[Condition]
allowed_actions: list[string]
handoff_conditions: list[HandoffCondition]
fallback_message: string
response_templates: list[ResponseTemplate]

approved_by: string | null
approved_at: datetime | null
published_by: string | null
published_at: datetime | null
scheduled_publish_at: datetime | null
archived_by: string | null
archived_at: datetime | null
supersedes_version_id: string | null
rollback_target_version_id: string | null
created_by: string
created_at: datetime
```

### Invariants

- Published versions are immutable.
- A call records the exact `scenario_version_id` used.
- `handoff_conditions` must include `customer_requested_human` and `insufficient_evidence` defaults even if not shown in UI.

## Entity: HandoffPackage

Information passed to human operators.

### Fields

```text
tenant_id: string
handoff_package_id: string
call_id: string
created_at: datetime
status: "created" | "queued" | "accepted" | "failed" | "unavailable" | "abandoned" | "callback_requested"

reason: string
priority: "low" | "normal" | "high" | "urgent"
destination_type: "queue" | "department" | "operator" | "external"
destination_id: string

caller_phone_number_masked: string | null
customer_id: string | null
intent: string | null
summary: string
transcript_excerpt_redacted: string
confirmed_slots: map
citations: list[PhoneCitationRef]
sentiment: string | null
recommended_next_action: string | null

operator_id: string | null
accepted_at: datetime | null
failure_reason: string | null
```

### Invariants

- `summary`, `reason`, and `destination_id` are required.
- Handoff package cannot expose raw secrets/card data.
- If `reason=customer_requested_human`, the package must be created even when AI could answer.

## Entity: QualityEvaluation

Supervisor review of a call.

### Fields

```text
tenant_id: string
evaluation_id: string
call_id: string
reviewer_id: string
reviewed_at: datetime

answer_correctness: 1..5 | null
tone_score: 1..5 | null
handoff_appropriateness: 1..5 | null
compliance_issue: boolean
hallucination_detected: boolean
privacy_issue: boolean
suggested_fix: string | null
knowledge_gap_topics: list[string]
review_status: "open" | "actioned" | "dismissed"
improvement_item_id: string | null
```

### Invariants

- `hallucination_detected=true` requires `suggested_fix` or `knowledge_gap_topics`.
- QA review access is audited.

## Entity: CallMetricSnapshot

Aggregated call-center metrics.

### Fields

```text
tenant_id: string
snapshot_id: string
bucket_start: datetime
bucket_end: datetime
dimensions: map                 # queue, scenario_id, intent, provider, channel

call_count: number
answered_count: number
abandoned_count: number
ai_completed_count: number
handoff_count: number
unresolved_count: number

answer_rate: number
abandonment_rate: number
service_level_rate: number
average_handle_time_seconds: number
after_contact_work_seconds: number | null
first_contact_resolution_rate: number | null
ai_containment_rate: number
handoff_rate: number
csat_average: number | null

top_handoff_reasons: list[MetricPair]
top_intents: list[MetricPair]
knowledge_gap_topics: list[MetricPair]

p95_asr_latency_ms: number | null
p95_rag_latency_ms: number | null
p95_llm_latency_ms: number | null
p95_tts_latency_ms: number | null
p95_total_turn_latency_ms: number | null
```

## Entity: ProviderConfig

Tenant/runtime configuration for phone providers and safety boundaries.

### Fields

```text
tenant_id: string
config_id: string
runtime_profile: "deterministic" | "staging" | "production"

telephony_provider: string
asr_provider: string
tts_provider: string
handoff_provider: string
crm_provider: string | null

business_hours: map
holiday_calendar_ref: string | null
recording_policy: map
retention_policy_ref: string
no_train_policy_ref: string
export_policy: map
deletion_policy_ref: string | null
allowed_intents: list[string]
blocked_intents: list[string]

created_at: datetime
updated_at: datetime
```

### Invariants

- `deterministic` profile uses no network/cloud/billed providers.
- `production` provider settings require explicit configuration and audit.

## State Machines

### CallSession

```text
ringing
  -> active
  -> on_hold -> active
  -> handoff_pending -> transferred
  -> completed
  -> abandoned
  -> failed
```

### AI turn action

```text
caller_input
  -> classify_intent
  -> evaluate_scenario_slots
  -> retrieve_evidence when answerable
  -> decide:
       ask_clarification
       answer_with_citations
       handoff
       fallback
       end_call
```

### ScenarioVersion

```text
draft -> in_review -> approved -> scheduled -> published -> archived
draft -> in_review -> approved -> published -> archived
```

Published scenario versions are immutable. Rollback publishes a previous version again or creates a new version referencing `rollback_target_version_id`.

## Relationships

- `CallSession 1 -> N ConversationTurn`
- `CallSession 0..1 -> HandoffPackage`
- `CallSession N -> 1 ScenarioVersion`
- `CallScenario 1 -> N ScenarioVersion`
- `CallSession 0..N -> QualityEvaluation`
- `ConversationTurn N -> N PhoneCitationRef -> Document/Chunk`
- `QualityEvaluation 0..1 -> KnowledgeImprovementItem` (existing improvement workflow)
- `CallMetricSnapshot` aggregates `CallSession`, `ConversationTurn`, `HandoffPackage`, and `QualityEvaluation`

## Reused Existing Models

- `Document` / `Chunk` / citation identifiers from 001 base platform.
- Manufacturing approval metadata patterns where "approved/effective evidence" is relevant; phone feature should generalize "current permitted evidence" without weakening manufacturing rules.
- Existing no-train, audit, provider policy, evaluation, and dashboard concepts.

## Privacy and Redaction Notes

- Default display/export should use masked phone number and redacted transcript.
- Raw audio refs and full transcript require privileged roles and audit.
- Card numbers, credentials, auth tokens, and internal headers must never appear in normal logs or exports.
- Deletion and retention must apply to call metadata, transcript, summaries, handoff packages, recordings, and derived exports.
