# Requirements Checklist: RAG-Connected Business ChatBot Agent

**Feature**: `023-rag-chatbot-agent`

**Date**: 2026-06-28

## Spec Completeness

- [x] Primary user value is described as a business conversation agent, not a simple FAQ bot.
- [x] Existing RAG reuse boundary is explicit.
- [x] ChatBot data source exposure is deny-by-default and narrower than generic RAG access.
- [x] MVP scope is bounded into P0/P1/P2.
- [x] User stories are independently testable and prioritized.
- [x] Acceptance scenarios cover grounded answers, slot filling, handoff, admin review, and analytics.
- [x] Edge cases cover prompt injection, low confidence, RAG failure, PII, tenant isolation, and duplicate actions.
- [x] Success criteria are measurable.

## Constitution Alignment

- [x] Groundedness-first behavior is explicit.
- [x] Traceability fields are required for bot answers and RAG interactions.
- [x] Tenant/ACL security is required before RAG calls, display, history, export, feedback, and handoff.
- [x] ChatBot does not duplicate ingestion, embedding, vector search, or knowledge approval.
- [x] Evaluation and feedback loops are part of the feature.
- [x] Observability and correlation IDs are required across the chat path.
- [x] API-first contract is drafted before UI.
- [x] Data lifecycle covers retention, redacted export, deletion/redaction, scenario versioning, and rollback.

## Resolved Boundaries

- [x] P0 uses deterministic non-streaming turn API; streaming is P1.
- [x] P0 Web Chat creates realtime feel without WebSocket using immediate message display, typing/progress states, timeout retry, and handoff affordances.
- [x] P0 uses ticket/handoff stubs; live CRM/ticket providers are P2.
- [x] P0 web chat only; Slack/LINE/Teams/phone channels are post-MVP.
- [x] P0 reuses existing RAG answer/search/feedback contracts.
- [x] P0 includes backend scenario lifecycle APIs; polished scenario management UI is P1.
- [x] P0 includes data source / collection ChatBot exposure policy for internal, external authenticated, and external anonymous chat modes.
- [x] `initial_message` is processed as the first turn when present.
- [x] ChatBot `answerable`/`no_answer_reason` are derived from existing RAG `AnswerResponse.status` unless the shared DTO is explicitly extended.
- [x] API versioning follows the existing `api-version` response header; body `api_version` is a convenience alias only.
- [x] Complex identity verification and state-changing business actions are not self-served in P0.

## Remaining Open Questions

- [ ] Choose first live ticketing/CRM provider adapter, if any.
- [ ] Choose first post-web channel: Slack/Teams/LINE or phone-history integration.
- [ ] Decide whether multi-language must ship before live CRM/business action integration.

## Risk Notes

- [x] Live/billed provider calls are not required for Tier A.
- [x] High-risk requests are handoff/ticket, not self-service completion.
- [x] Prompt injection is handled by server-side guardrails, not prompt text alone.
- [x] Human-requested handoff is a hard rule.
- [x] RAG/provider failure has fail-closed fallback semantics.
- [x] Disabled or non-public data sources cannot be used by external/anonymous ChatBot even if they exist in the RAG index.
