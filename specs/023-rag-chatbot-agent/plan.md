# Implementation Plan: RAG-Connected Business ChatBot Agent

**Branch**: `023-rag-chatbot-agent` | **Date**: 2026-06-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/023-rag-chatbot-agent/spec.md`

## Summary

Build a business conversation ChatBot layer on top of the existing raku-rag platform. The feature adds Web Chat UI/API contracts, session/state management, intent classification, scenario/slot orchestration, backend scenario lifecycle APIs, existing RAG connector, guardrails, human handoff/ticket stubs, conversation history, response review, and operational metrics.

The feature does not create another RAG stack. Existing 001 platform capabilities own ingestion, embeddings, retrieval, grounded answer generation, citations, ACL pre-filtering, deletion, feedback, provider policy, and RAG observability. The ChatBot layer owns conversation progress and business workflow state.

## Technical Context

**Language/Version**: Python 3.11+ core under `src/raku_rag/`; NestJS API under `apps/api/`; Next.js web under `apps/web/`; shared TypeScript DTOs under `packages/shared`.

**Primary Dependencies**: Existing `AnswerService`/search/answer contracts and shared DTOs, tenant/auth middleware, provider policy, logging/redaction, feedback/evaluation patterns, NestJS facade, Next.js app shell, Postgres/RLS, S3/export patterns, SQS worker patterns where asynchronous ticket/export jobs are needed.

**Storage**: Postgres for chat sessions, messages, conversation states, scenario versions, RAG interaction logs, handoff packages, ticket stubs, feedback/evaluations, metric snapshots, audit events. Existing RAG Document/Chunk/vector storage is reused and not duplicated.

**Testing**: Python unittest via `scripts/gate.sh a/all`; security tests for tenant/ACL/PII/prompt injection; contract tests under `tests/contract`; NestJS e2e via `npm run test:api`; web typecheck/build; deterministic scenario integration tests.

**Target Platform**: Existing raku-rag web/API/service stack. P0 must run locally with deterministic RAG fixtures and must not require live CRM, Slack, ticketing, WebSocket, cloud, or billed provider calls for Tier A.

**Project Type**: Monorepo web-service + frontend admin/customer UI.

**Performance Goals**:

- First UI acknowledgement within 1s in deterministic/local tests.
- Non-streaming P0 bot response p95 under 3s with deterministic RAG connector.
- Session detail retrieval p95 under 1s for seeded P0 data.
- Dashboard query p95 under 1s for seeded P0 data.

**Constraints**:

- Tier A remains stdlib/fast; no Docker, network, cloud, DB, or heavy dependency requirements added to `scripts/gate.sh a`.
- Tenant/ACL boundaries are enforced before RAG calls, answer display, citations, session history, admin history, export, feedback, and handoff.
- ChatBot cannot answer without grounded RAG evidence for knowledge claims.
- ChatBot cannot create a parallel ingestion/vector/approval path.
- PII and secrets must not leak to logs, traces, model prompts, exports, or default admin views.
- Live CRM/ticket/notification providers and production deployment remain explicitly configured and human-gated.

**Scale/Scope**:

- P0 product MVP: web chat, deterministic scenarios, backend scenario lifecycle APIs, existing RAG connector adapter, ticket/handoff stubs, history, review, basic metrics.
- P1: scenario admin UI/editor, streaming, notification adapter, unanswered/review queue.
- P2: live CRM/business APIs, multi-channel, live operator takeover, A/B testing, phone history integration.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Groundedness First**: PASS. ChatBot only makes knowledge claims via existing RAG grounded answer/citation behavior; insufficient evidence triggers clarification or handoff.
- **II. Traceability**: PASS. Every grounded bot answer stores session/message/correlation IDs plus RAG trace IDs and citation identifiers.
- **III. Security by Design**: PASS. Tenant/ACL, PII masking, no-train, retention, audit, and handoff visibility are first-class requirements.
- **IV. Pluggable Architecture**: PASS. RAG, business actions, ticketing, handoff, notification, and streaming are interfaces/adapters with deterministic defaults.
- **V. Evaluation-Gated Delivery**: PASS. Scenario probes, RAG insufficiency probes, handoff probes, prompt-injection probes, redaction probes, and KPI checks are required.
- **VI. Observable by Default**: PASS. Session spans connect chat API, orchestrator, scenario, RAG, guardrail, handoff/ticket, persistence, and metrics.
- **VII. API First**: PASS. Public and internal chat contracts are designed before UI.
- **VIII. Data Lifecycle Complete**: PASS. Retention, export, deletion/redaction, versioning, scenario rollback, and derived analytics lifecycle are included.

No constitution violations are currently accepted.

## Project Structure

### Documentation (this feature)

```text
specs/023-rag-chatbot-agent/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── chat-openapi.md
├── checklists/
│   └── requirements.md
└── tasks.md                 # created later by /speckit-tasks
```

### Source Code (repository root)

```text
src/raku_rag/
├── chatbot/
│   ├── __init__.py
│   ├── domain.py             # ChatSession, ChatMessage, state, scenario, handoff, ticket models
│   ├── interfaces.py         # RAG, scenario, ticket, handoff, notification, metrics contracts
│   ├── orchestrator.py       # turn execution and conversation state machine
│   ├── intents.py            # deterministic intent classifier and prioritization
│   ├── scenarios.py          # scenario validation, versioning, preview, publish/rollback
│   ├── slots.py              # slot extraction, validation, correction, confirmation
│   ├── rag_connector.py      # adapter to existing answer/search service contracts
│   ├── guardrails.py         # high-risk, prompt injection, policy decisions
│   ├── handoff.py            # handoff package and ticket stub creation
│   ├── redaction.py          # chat-specific masking/projections
│   ├── quality.py            # feedback/review bridge to existing RAG improvement flow
│   └── metrics.py            # chatbot KPI aggregation
└── persistence/
    └── chatbot_models.py     # Postgres/RLS persistence for chat entities

apps/answer-service/
└── server.py                 # internal /internal/chat/* routes composed with existing answer/search

apps/api/src/
├── chat/                     # NestJS facade: /v1/chat/*
└── openapi/                  # OpenAPI schema additions

apps/web/app/components/
└── FullSaasScreen.tsx        # initial customer/admin chat surfaces if kept in current shell

packages/shared/src/dto/
└── chat.ts                   # shared DTOs for sessions/messages/scenarios/handoffs/metrics

tests/
├── unit/test_chatbot_*.py
├── contract/test_chat_openapi.py
├── security/test_chatbot_*.py
└── integration/test_chatbot_*.py

apps/api/test/
└── chat.e2e-spec.ts
```

**Structure Decision**: Add a new `chatbot` solution layer that composes the existing RAG answer/search services. Keep conversation state and business workflow separate from generic RAG services. Expose the feature through the existing NestJS facade and shared DTO package.

## Phase 0 Research Plan

1. Decide the P0 runtime model:
   - deterministic HTTP-style chat turn API
   - no mandatory WebSocket/SSE in P0
   - existing RAG connector over current internal answer/search contracts and shared DTOs
2. Decide conversation orchestrator boundaries:
   - when to classify intent
   - when to fill slots
   - when to call RAG
   - when to hand off or create a ticket
3. Decide scenario/versioning and approval model.
4. Decide handoff/ticket package shape and operator workflow.
5. Decide chat data lifecycle: retention, redacted export, deletion/redaction request.
6. Decide which existing RAG/admin screens and feedback flows can be reused.

## Phase 1 Design Outputs

- [research.md](research.md): reuse, orchestration, scenario, handoff, data lifecycle, and MVP boundary decisions.
- [data-model.md](data-model.md): ChatSession, ChatMessage, ConversationState, scenarios, slots, RAG interactions, handoffs, feedback, metrics.
- [contracts/chat-openapi.md](contracts/chat-openapi.md): public API and internal facade contracts.
- [quickstart.md](quickstart.md): deterministic local demo and acceptance smoke.

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| ChatBot reimplements RAG and drifts from ACL/groundedness | Tenant leak or hallucinated answers | RAG connector only; contract tests pin existing answer/search reuse |
| Bot completes unsafe business action | Customer/commercial harm | final confirmation + idempotency + high-risk handoff |
| PII leaks in chat logs/admin/handoff | Compliance risk | redacted projections, privileged access audit, PII tests |
| Prompt injection manipulates system/tool behavior | Data/action leak | guardrail tests; user/RAG text never treated as system instructions |
| Scenario drift causes wrong conversation | Bad UX/compliance | versioning, approval, preview, rollback |
| RAG outage creates confident fallback | Hallucination risk | fail-closed fallback or handoff; no definitive answer |
| ChatBot assumes RAG fields that the existing DTO does not expose | Contract drift and duplicated RAG API | Adapter maps existing `status`/citations/freshness to chat metadata; any RAG DTO extension must update `packages/shared` and OpenAPI first |
| Scope grows into CRM/CCaaS platform | Delivery risk | deterministic stubs in P0; live adapters post-MVP |

## Complexity Tracking

No constitution violations are currently planned. The feature is broad, but complexity is constrained by reusing existing RAG primitives and slicing live integrations behind adapters.
