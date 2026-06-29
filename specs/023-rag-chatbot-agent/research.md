# Research: RAG-Connected Business ChatBot Agent

**Feature**: `023-rag-chatbot-agent`

**Date**: 2026-06-28

## Decision 1: ChatBot is a conversation orchestrator, not a new RAG stack

**Decision**: The ChatBot layer calls existing RAG answer/search/feedback contracts. It does not own ingestion, embedding, vector search, groundedness, document approval, ACL, deletion, or RAG evaluation. P0 adapts the current shared DTOs rather than requiring a new RAG request/response shape.

**Rationale**:

- The 001 RAG platform already owns tenant isolation, ACL pre-filtering, grounded answer generation, citations, deletion/tombstone behavior, provider policy, and feedback.
- Reimplementing retrieval in ChatBot would create a second security boundary and increase ACL/deletion regression risk.
- `goal.md` says "RAGは答えるために使う。ChatBotは会話を最後まで進めるために使う。"
- Existing 001 `AnswerResponse.status` already distinguishes `ok`, `insufficient_evidence`, `budget_exceeded`, and `temporarily_unavailable`; ChatBot can derive `answerable` and handoff/fallback behavior from that status.

**Alternatives considered**:

- Build a ChatBot-specific vector store: rejected because it duplicates ACL/approval/deletion and makes RAG quality diverge.
- Let the frontend call RAG directly: rejected because conversation state, slot validation, guardrails, and handoff require server-side control.

## Decision 2: P0 uses deterministic turn API; streaming is P1

**Decision**: P0 exposes a deterministic `POST /v1/chat/sessions/{session_id}/messages` turn API. SSE/WebSocket streaming can be added in P1 using the same message and event DTOs.

P0 realtime feel is a UI responsibility: render the sent user message immediately, show bot typing/progress labels while the HTTP request is pending, then show retry or human handoff when delay/timeout thresholds are reached.

**Rationale**:

- Deterministic turn APIs are easier to test in Tier A/API e2e.
- The primary P0 risk is correctness/safety, not streaming UX.
- Streaming can be added without changing persisted message/state contracts.
- HTTP request/response keeps auth, tenant context, idempotency, retries, and error handling easier to test for the first release.

**Alternatives considered**:

- WebSocket-first: rejected for P0 because it adds connection lifecycle complexity before orchestration safety is proven.
- SSE-first: rejected for P0 because token streaming does not solve the harder state/groundedness/handoff guarantees; it remains a P1 enhancement.
- Async job plus polling: deferred until a real long-running workflow requires it; if introduced, it must reuse the same client response states.
- Browser-only state: rejected because session/state/handoff/audit must be server authoritative.

## Decision 3: Scenario and slot engine are versioned from the start

**Decision**: Chat scenarios have logical records plus immutable versions. Published versions are immutable, and each session/message records the scenario version used.

**Rationale**:

- Business workflows change over time; support teams need preview, approval, rollback, and audit.
- Past conversations must remain explainable against the exact scenario that drove them.
- The same safety idea exists in the phone spec and manufacturing draft/approval patterns.

**Alternatives considered**:

- Store scenario JSON directly on the session: rejected because it is hard to manage, approve, and roll back.
- Hard-code P0 scenarios only: rejected because scenario versioning is central to "業務対話エージェント".

## Decision 4: Business actions are P0 ticket stubs unless explicitly enabled

**Decision**: P0 can create deterministic ticket/follow-up stubs after explicit user confirmation. Live CRM, billing, cancellation, reservation, Slack/email, or other external actions are adapter seams for later phases.

**Rationale**:

- State-changing business APIs require identity verification, authorization, idempotency, audit, and tenant-specific integration.
- P0 can still demonstrate end-to-end workflow by creating a ticket stub and handoff package.
- This avoids accidentally making a demo bot perform real cancellation/refund/account actions.

**Alternatives considered**:

- Implement real cancellation/billing APIs in P0: rejected as too high-risk and tenant-specific.
- No ticket action at all: rejected because `goal.md` requires handoff/procedure completion beyond Q&A.

## Decision 5: HandoffPackage is first-class

**Decision**: Handoff is persisted as a package with summary, transcript, slots, missing slots, RAG citations, confidence, reason, priority, and recommended action.

**Rationale**:

- Users should not repeat the same explanation after handoff.
- Operators need enough context to continue safely.
- Handoff outcomes feed metrics and RAG/scenario improvement.

**Alternatives considered**:

- Store only a handoff status on the session: rejected because it loses operator context.

## Decision 6: Prompt injection and tool authorization are server-side guardrails

**Decision**: User text, retrieved context, and tool output are never treated as system instructions. Tool/business action execution requires explicit scenario permission, identity/role checks, final user confirmation, and idempotency.

**Rationale**:

- A ChatBot has more attack surface than a simple answer endpoint because it can collect PII, create tickets, and eventually call tools.
- The existing RAG security boundary protects retrieval, but the ChatBot must protect workflow state and actions.

**Alternatives considered**:

- Rely on LLM prompt instructions alone: rejected because prompt-only controls are not stable enough for business actions.

## Decision 7: Chat data is transcript-first with redacted projections

**Decision**: P0 persists message history, state, redacted text, citations, handoff/ticket data, feedback, and metrics. Raw sensitive fields require privileged access and audit. Retention/export/deletion are explicit ChatBot contracts.

**Rationale**:

- Chat logs can contain email, phone, company, contract IDs, account details, and secrets.
- Admins need enough data for review, but default displays and exports should be redacted.
- The data lifecycle must be explicit because chat sessions generate derived state and analytics beyond RAG documents.

**Alternatives considered**:

- Do not store chat history: rejected because handoff, review, and analytics require it.
- Store everything raw by default: rejected due to compliance and leakage risk.

## Decision 8: Feedback bridges to existing RAG improvement flow

**Decision**: Chat evaluations and user feedback link to chat messages, RAG interactions, and citations, then flow into existing RAG feedback/improvement mechanisms when issue type indicates RAG gap or wrong evidence.

**Rationale**:

- ChatBot is a consumer of RAG, so RAG gaps discovered in chat should improve the shared knowledge base.
- Keeping feedback connected avoids a separate "chat only" quality backlog.

**Alternatives considered**:

- Independent ChatBot evaluation store only: rejected because it would disconnect root-cause fixes from RAG content/retrieval.

## Decision 9: ChatBot source access is datasource-policy gated

**Decision**: ChatBot can use only data sources/collections explicitly enabled for the current chat mode. Effective access is the intersection of existing RAG ACL and lifecycle checks, data source ChatBot exposure policy, scenario filters, and channel/public widget restrictions.

**Rationale**:

- External ChatBot access is a narrower trust boundary than internal RAG search.
- A tenant may want a data source indexed for employees but never exposed through public chat.
- Data source owners need a clear UI setting: disabled, internal authenticated, external authenticated, or external anonymous.
- Keeping this as an extra policy avoids creating a second vector store while still giving product-level control.

**Alternatives considered**:

- Rely only on existing ACL: rejected because ACL may permit internal users while the business does not want that source used by ChatBot.
- Copy public documents into a separate ChatBot index: rejected because it duplicates ingestion, deletion, approval, and ACL behavior.
- Let scenario filters alone decide source access: rejected because scenarios are workflow logic, not the source-of-truth for data exposure.

## Resolved MVP Boundaries

1. P0 is web chat only. LINE, Slack, Teams, phone, and Amazon Connect integration are post-MVP adapters.
2. P0 uses deterministic ticket/handoff stubs. Live CRM/business action providers are not required.
3. P0 uses non-streaming turn API with immediate UI acknowledgement, typing/progress labels, timeout retry, and handoff UX. Streaming is P1.
4. P0 includes backend scenario lifecycle APIs, basic admin session detail, and review; the full scenario editor UI and dashboard polish are P1.
5. P0 is Japanese-capable through existing RAG Japanese retrieval and deterministic scenario prompts.
6. P0 supports anonymous chat only when tenant policy explicitly enables restricted anonymous mode.
7. P0 supports data source ChatBot exposure policy for source/collection allowlisting; full datasource-management UI polish can follow existing admin patterns.

## Remaining Open Questions

1. Which live ticketing/CRM provider should be the first production adapter, if any.
2. Whether the first user-facing channel after web chat should be Slack/Teams/LINE or phone-history integration.
3. Whether multi-language support is required before live CRM/business action integration.
