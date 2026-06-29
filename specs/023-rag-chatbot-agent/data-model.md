# Data Model: RAG-Connected Business ChatBot Agent

**Feature**: `023-rag-chatbot-agent`

**Date**: 2026-06-28

## Overview

This feature adds ChatBot-specific entities while reusing the existing RAG platform:

- Existing RAG path: `Document`, `Chunk`, visual assets, ACL, citations, retrieval, answer generation, groundedness, deletion, feedback, evaluation.
- New ChatBot path: sessions, messages, conversation state, chat scenarios, slot values, RAG interaction logs, handoff packages, ticket stubs, chat evaluations, metrics, provider config, and source exposure policy.

Every ChatBot entity is tenant-scoped and traceable by correlation ID.

## Entity: ChatSession

Represents one customer chat conversation.

### Fields

```text
tenant_id: string
session_id: string
correlation_id: string
channel: "web_chat" | "slack" | "line" | "teams" | "phone_bridge" | string

user_id: string | null
anonymous_id: string | null
customer_id: string | null
customer_display_name: string | null
customer_email_masked: string | null
company_name: string | null

status: "active" | "waiting_user" | "handoff_pending" | "ticket_created" | "resolved" | "abandoned" | "failed"
current_intent: string | null
intent_confidence: number | null
current_scenario_id: string | null
current_scenario_version_id: string | null
current_step_id: string | null

started_at: datetime
last_message_at: datetime
ended_at: datetime | null
resolution_status: "resolved" | "unresolved" | "transferred" | "ticket_created" | "abandoned" | "failed" | null
handoff_required: boolean
handoff_package_id: string | null
ticket_id: string | null
summary_redacted: string | null
csat_score: number | null

retention_policy_ref: string | null
no_train_policy_ref: string | null
created_at: datetime
updated_at: datetime
```

### Invariants

- `tenant_id + session_id` is unique.
- `correlation_id` propagates to messages, RAG interactions, handoffs, tickets, audit, and metrics.
- Terminal statuses are `resolved`, `abandoned`, and `failed`; new user messages may reopen only through explicit resume logic.
- `current_scenario_version_id` used for a processed message is immutable for that message.

## Entity: ChatMessage

Represents a user, assistant, system, or operator message.

### Fields

```text
tenant_id: string
session_id: string
message_id: string
sequence_no: number
role: "user" | "assistant" | "system" | "operator"
message_type: "text" | "form" | "quick_reply" | "handoff_notice" | "ticket_notice" | "error"

raw_content_ref: string | null
content_redacted: string
content_hash: string
language: string
quick_replies: list[QuickReply]
form_schema: map | null

intent: string | null
scenario_id: string | null
scenario_version_id: string | null
step_id: string | null
ai_action: "ask_clarification" | "answer_with_citations" | "collect_slot" | "confirm_action" | "handoff" | "create_ticket" | "fallback" | "end_session" | null

citations: list[ChatCitationRef]
rag_interaction_id: string | null
handoff_package_id: string | null
ticket_id: string | null
guardrail_decision: map | null

latency_ms: map
token_count: number | null
created_at: datetime
```

### Invariants

- `sequence_no` is monotonic per session.
- Assistant messages with `answer_with_citations` must carry at least one valid citation.
- `content_redacted` is the default display/export value.

## Entity: ConversationState

Current state for a session.

### Fields

```text
tenant_id: string
session_id: string
state_id: string
current_intent: string | null
current_scenario_id: string | null
current_scenario_version_id: string | null
current_step_id: string | null

collected_slots: map
missing_slots: list[string]
slot_failure_counts: map
last_user_message_id: string | null
last_assistant_message_id: string | null
last_rag_interaction_id: string | null
context_summary_redacted: string | null

handoff_required: boolean
handoff_reason: string | null
status: "in_progress" | "waiting_user" | "waiting_operator" | "completed" | "failed"
updated_at: datetime
```

### Invariants

- State updates are append-audited or versioned enough to reconstruct decisions.
- Sensitive slot values are masked by default.

## Entity: ChatScenario

Logical scenario selected by intent and entry conditions.

### Fields

```text
tenant_id: string
scenario_id: string
name: string
description: string | null
primary_intent: string
status: "draft" | "in_review" | "approved" | "scheduled" | "published" | "archived"
active_version_id: string | null
owner_group: string | null
created_by: string
created_at: datetime
updated_at: datetime
```

## Entity: ChatScenarioVersion

Immutable scenario definition.

### Fields

```text
tenant_id: string
scenario_id: string
scenario_version_id: string
version_number: number
status: "draft" | "in_review" | "approved" | "scheduled" | "published" | "archived"

entry_conditions: list[Condition]
intent_priority: number
steps: list[ScenarioStep]
slot_definitions: list[SlotDefinition]
rag_policy: map
handoff_conditions: list[HandoffCondition]
business_actions: list[BusinessActionDefinition]
response_templates: list[ResponseTemplate]
fallback_policy: map

approved_by: string | null
approved_at: datetime | null
published_by: string | null
published_at: datetime | null
scheduled_publish_at: datetime | null
supersedes_version_id: string | null
rollback_target_version_id: string | null
created_by: string
created_at: datetime
```

### Invariants

- Published versions are immutable.
- Publication requires approved state.
- Every active scenario has default handoff conditions for `customer_requested_human`, `insufficient_evidence`, and `guardrail_blocked`.

## Entity: SlotDefinition

Definition of a value the Bot may collect.

```text
slot_name: string
label: string
required: boolean
value_type: "string" | "email" | "phone" | "number" | "date" | "enum" | "boolean"
sensitive_class: "none" | "pii" | "secret" | "payment" | "contract"
validation_rules: map
max_attempts: number
confirmation_required: boolean
skip_behavior: "allow_skip" | "handoff" | "block"
```

## Entity: SlotValue

Collected slot value for a session.

```text
tenant_id: string
session_id: string
slot_name: string
value_redacted: string | null
value_hash: string | null
raw_value_ref: string | null
status: "collected" | "validated" | "corrected" | "skipped" | "failed"
source_message_id: string
confirmed_by_user: boolean
updated_at: datetime
```

### Invariants

- Sensitive slot values default to redacted display.
- Corrections preserve enough audit trail to explain final values.

## Entity: RagInteraction

Chat-side record of an existing RAG call.

```text
tenant_id: string
rag_interaction_id: string
session_id: string
message_id: string
correlation_id: string
rag_trace_id: string | null

query_redacted: string
conversation_summary_redacted: string | null
intent: string | null
scenario_id: string | null
scenario_version_id: string | null
filters: map
allowed_source_ids: list[string]
allowed_collection_ids: list[string]
exposure_policy_id: string | null
rag_endpoint: "answer" | "search"

status: "ok" | "insufficient_evidence" | "budget_exceeded" | "temporarily_unavailable" | "error"
answer_redacted: string | null
answerable: boolean          # derived from existing RAG status + citation validity
confidence: number | null
no_answer_reason: string | null  # derived from status when generic RAG has no explicit field
risk_flags: list[string]         # ChatBot guardrail/product-extension flags
citations: list[ChatCitationRef]
latency_ms: number | null
created_at: datetime
```

### Invariants

- `tenant_id` and signed user claims are never taken from public request bodies.
- RAG citations are references to existing RAG identifiers, not copied knowledge ownership.
- Generic 001 `AnswerResponse.status` is the source field; ChatBot `answerable` and `no_answer_reason` are adapter-derived unless the shared RAG DTO is explicitly extended.
- `allowed_source_ids`, `allowed_collection_ids`, and `exposure_policy_id` are server-derived from scenario and tenant datasource policy; public request bodies cannot set them.

## Value Object: ChatCitationRef

```text
source_id: string
document_id: string
chunk_id: string
version: number | null
retrieval_score: number
title: string | null
url: string | null
page_number: number | null
snippet_redacted: string | null
freshness: map | null
```

`title`, `url`, and `snippet_redacted` are optional display projections. They are not required from the generic 001 citation DTO unless fetched through an existing citation/source view.

## Entity: HandoffPackage

Information passed to humans or ticket queues.

```text
tenant_id: string
handoff_package_id: string
session_id: string
created_at: datetime
status: "created" | "queued" | "accepted" | "ticket_created" | "failed" | "abandoned"
reason: string
priority: "low" | "normal" | "high" | "urgent"
destination_type: "operator_queue" | "ticket_queue" | "email" | "slack" | "external"
destination_id: string

customer_display_redacted: map
intent: string | null
summary_redacted: string
transcript_redacted: list[MessageExcerpt]
collected_slots_redacted: map
missing_slots: list[string]
rag_citations: list[ChatCitationRef]
rag_confidence: number | null
recommended_action: string | null

operator_id: string | null
accepted_at: datetime | null
failure_reason: string | null
```

## Entity: TicketStub

Deterministic P0 ticket/follow-up record.

```text
tenant_id: string
ticket_id: string
session_id: string
idempotency_key: string
status: "created" | "queued" | "sent" | "failed" | "cancelled"
ticket_type: "support" | "sales" | "billing" | "cancellation" | "technical"
summary_redacted: string
payload_redacted: map
created_by: "bot" | "operator" | "admin"
created_at: datetime
```

### Invariants

- `idempotency_key` prevents duplicate ticket creation for the same confirmed action.
- Live external ticket provider references are optional and post-MVP.

## Entity: ChatEvaluation

User or reviewer feedback.

```text
tenant_id: string
evaluation_id: string
session_id: string
message_id: string | null
reviewer_id: string | null
source: "user_feedback" | "reviewer" | "eval_job"
rating: 1..5 | null
correctness_score: 1..5 | null
tone_score: 1..5 | null
grounding_score: 1..5 | null
handoff_appropriateness: 1..5 | null
issue_type: "rag_gap" | "wrong_answer" | "scenario_gap" | "tone" | "handoff" | "privacy" | "other" | null
comment_redacted: string | null
improvement_item_id: string | null
created_at: datetime
```

## Entity: ChatMetricSnapshot

Aggregated KPI snapshot.

```text
tenant_id: string
snapshot_id: string
bucket_start: datetime
bucket_end: datetime
dimensions: map       # channel, scenario_id, intent

conversation_count: number
bot_resolved_count: number
handoff_count: number
unanswered_count: number
abandoned_count: number
ticket_created_count: number

bot_resolution_rate: number
handoff_rate: number
unanswered_rate: number
abandonment_rate: number
scenario_completion_rate: number
rag_answerable_rate: number
rag_low_confidence_rate: number
average_turns: number
average_response_latency_ms: number
p95_response_latency_ms: number
csat_average: number | null

top_intents: list[MetricPair]
top_handoff_reasons: list[MetricPair]
top_rag_gap_topics: list[MetricPair]
error_rate: number
```

## Entity: ChatbotProviderConfig

Tenant/runtime settings.

```text
tenant_id: string
config_id: string
runtime_profile: "deterministic" | "staging" | "production"
rag_connector: string
business_action_provider: string
handoff_provider: string
notification_provider: string | null
anonymous_chat_enabled: boolean
anonymous_acl_scope: map | null
public_widget_allowed_domains: list[string]
default_source_exposure_mode: "disabled" | "internal_authenticated"
retention_policy_ref: string
no_train_policy_ref: string
logging_policy_ref: string
allowed_intents: list[string]
blocked_intents: list[string]
created_at: datetime
updated_at: datetime
```

## Entity: ChatbotSourceExposurePolicy

Tenant-scoped policy deciding whether a data source or collection can be used by ChatBot.

```text
tenant_id: string
policy_id: string
source_id: string | null
collection_id: string | null
exposure_mode: "disabled" | "internal_authenticated" | "external_authenticated" | "external_anonymous"
allowed_channels: list[string]       # web_chat, public_widget, customer_portal, etc.
allowed_scenario_ids: list[string]
allowed_intents: list[string]
required_document_tags: list[string]
blocked_document_tags: list[string]
require_approved_effective: boolean
allow_obsolete_primary_evidence: boolean
public_widget_key_ids: list[string]
allowed_domains: list[string]
configured_by: string
configured_at: datetime
updated_at: datetime
```

### Invariants

- Default exposure is `disabled` unless tenant config explicitly opts into an internal default.
- `external_anonymous` requires `anonymous_chat_enabled`, domain/widget validation, explicit source/collection exposure, and restricted ACL scope.
- `external_anonymous` must require approved/effective evidence and must not allow obsolete, draft, review-required, private, or internal-only primary evidence.
- Existing RAG ACL remains mandatory; exposure policy never grants access by itself.
- If multiple policies match, the most restrictive effective policy wins.

## State Machines

### ChatSession

```text
active
  -> waiting_user
  -> handoff_pending -> ticket_created
  -> resolved
  -> abandoned
  -> failed
```

### Turn execution

```text
user_message
  -> redact_and_store
  -> classify_intent
  -> select_scenario
  -> extract_slots
  -> validate_slots
  -> decide:
       ask_clarification
       call_rag
       answer_with_citations
       confirm_action
       create_ticket
       handoff
       fallback
       end_session
```

### ScenarioVersion

```text
draft -> in_review -> approved -> scheduled -> published -> archived
draft -> in_review -> approved -> published -> archived
```

## Relationships

- `ChatSession 1 -> N ChatMessage`
- `ChatSession 1 -> 1 ConversationState`
- `ChatSession N -> 1 ChatScenarioVersion`
- `ChatScenario 1 -> N ChatScenarioVersion`
- `ChatSession 0..N -> RagInteraction`
- `RagInteraction N -> N ChatCitationRef -> existing Document/Chunk`
- `RagInteraction N -> 1 ChatbotSourceExposurePolicy` when a source/collection exposure policy was applied.
- `ChatSession 0..1 -> HandoffPackage`
- `ChatSession 0..N -> TicketStub`
- `ChatSession 0..N -> ChatEvaluation`
- `ChatMetricSnapshot` aggregates sessions, messages, RAG interactions, handoffs, tickets, and evaluations.

## Reused Existing Models

- Existing RAG `Document`, `Chunk`, citations, `used_chunks`, source freshness, and answer/search status.
- Existing tenant/auth principal, ACL policy, provider policy, no-train policy, redaction, audit, feedback, and evaluation concepts.
- Existing datasource, ingestion, embedding, vector store, deletion, and approval flows.

## Privacy and Lifecycle Notes

- Default UI/export uses redacted message text and masked slot values.
- Raw sensitive values require privileged role and audited access.
- P0 stores transcript/state because handoff, review, and analytics require them.
- Retention/deletion/redaction applies to sessions, messages, states, RAG interaction logs, handoffs, tickets, evaluations, exports, and metric derivations.
