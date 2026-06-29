# Implementation Plan: AI Phone RAG Contact Center

**Branch**: `022-ai-phone-rag` | **Date**: 2026-06-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/022-ai-phone-rag/spec.md`

## Summary

Build an AI phone response layer on top of the existing raku-rag platform. The feature adds telephony/ASR/TTS provider seams, a call conversation orchestrator, scenario management, human handoff packages, call history, QA review, and call-center KPI dashboards. Existing RAG ingestion, tenant isolation, ACL pre-filtering, citations, groundedness, no-train policy, audit patterns, provider factories, and admin UI should be reused wherever possible.

MVP scope is inbound phone calls for bounded low/medium-risk use cases: business hours, FAQ, pricing/plan explanation, reservation/order status lookup, document request, and department routing. High-risk, unsupported, angry, unclear, or human-requested calls must transfer to a human rather than force AI completion.

## Technical Context

**Language/Version**: Python 3.11+ core under `src/raku_rag/`; NestJS API under `apps/api/`; Next.js web under `apps/web/`; shared TypeScript DTOs under `packages/shared`.

**Primary Dependencies**: Existing raku-rag RAG services, provider interfaces/factories, NestJS facade, Next.js admin UI, Postgres/pgvector/RLS, SQS worker patterns. New provider abstractions for telephony, ASR, and TTS should follow existing LLM/embedding/provider policy patterns.

**Storage**: Postgres for call sessions, turns, scenario versions, handoff packages, QA reviews, metrics snapshots, audit events. S3-compatible object storage for optional recordings and large audio artifacts. Existing Document/Chunk/vector storage for knowledge.

**Testing**: Python unittest/pytest via `scripts/gate.sh a/all`; NestJS e2e via `npm run test:api`; web typecheck/build; contract tests under `tests/contract`; provider fake-client tests for telephony/ASR/TTS/handoff.

**Target Platform**: Production web/API/service stack already used by raku-rag. MVP must run locally with deterministic fake telephony/ASR/TTS providers and must not require live phone, cloud, or billed provider calls for Tier A.

**Project Type**: Monorepo web-service + worker + frontend admin application.

**Performance Goals**:

- Turn-level AI response should start within a configurable SLA after final ASR segment; MVP target p95 under 2.5s for deterministic/local providers.
- Handoff package generation should complete within 1s after handoff trigger in deterministic tests.
- Dashboard queries should return within 1s for seeded MVP data.

**Constraints**:

- Tier A remains stdlib/fast; no live telephony, network, cloud, DB, or heavy dependency requirements added to `scripts/gate.sh a`.
- Tenant/ACL boundaries must be enforced before retrieval, answer, citation display, call history, export, handoff package, and recording access.
- AI must not answer without grounded evidence in RAG-backed flows.
- Call audio/transcript/PII must not leak to logs, traces, provider payloads, or exports.
- No production/billed telephony, ASR, TTS, or LLM calls without explicit human approval and configuration.

**Scale/Scope**:

- P1 technical demo: one tenant, seeded knowledge, local phone-call simulator, bounded intents, grounded phone answers, safe handoff, and scenario operations.
- Product MVP from `goal.md`: P1 technical demo plus searchable redacted call history, QA review creation, basic KPI dashboard, and retention/export/deletion controls.
- Post-MVP: live CRM, real ACD/PBX/SIP/Amazon Connect adapters, complex identity verification, Agent Assist, multi-language, outbound, A/B testing, and VOC analytics.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Groundedness First**: PASS. AI phone answers are grounded in existing RAG citations; insufficient evidence triggers clarification or handoff.
- **II. Traceability**: PASS. Every call/turn/answer/handoff records call ID, correlation ID, scenario version, provider run IDs where available, and citation identifiers.
- **III. Security by Design**: PASS with safety-critical emphasis. Tenant/ACL, PII masking, retention, audit, and no-train controls are first-class requirements.
- **IV. Pluggable Architecture**: PASS. Telephony, ASR, TTS, CRM, and handoff are provider interfaces. Deterministic fakes are default for tests.
- **V. Evaluation-Gated Delivery**: PASS. MVP defines call-flow probes, handoff probes, insufficiency probes, redaction probes, latency/KPI checks.
- **VI. Observable by Default**: PASS. Call spans cover telephony → ASR → orchestration → retrieval → LLM → TTS → handoff → persistence.
- **VII. API First**: PASS. Contracts define call simulation, call history, scenario, handoff, QA, and metrics APIs before UI.
- **VIII. Data Lifecycle Complete**: PASS. Product MVP contracts include retention policy, redacted export, and deletion/redaction request surfaces; recording persistence remains optional and transcript-first.

No constitution violations are currently accepted.

## Project Structure

### Documentation (this feature)

```text
specs/022-ai-phone-rag/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── phone-rag-openapi.md
└── tasks.md                 # implementation task breakdown
```

### Source Code (repository root)

```text
src/raku_rag/
├── phone/
│   ├── domain.py             # CallSession, ConversationTurn, HandoffPackage value/domain models
│   ├── interfaces.py         # Telephony/ASR/TTS/Handoff/Scenario contracts
│   ├── orchestrator.py       # conversation state machine and turn execution
│   ├── scenarios.py          # scenario validation, versioning, publication rules
│   ├── handoff.py            # handoff rules and package generation
│   ├── redaction.py          # call transcript/audio metadata redaction helpers
│   ├── quality.py            # QA evaluation and improvement workflow bridge
│   └── metrics.py            # call KPI aggregation
├── providers/
│   ├── telephony.py          # deterministic simulator + production adapter seam
│   ├── asr.py                # deterministic transcript ASR + provider seam
│   └── tts.py                # deterministic TTS text/audio ref + provider seam
└── persistence/
    └── phone_models.py       # Postgres/RLS persistence for call entities

apps/answer-service/
└── server.py                 # internal phone endpoints routed to Python phone service

apps/api/src/
├── phone/                    # NestJS facade: /v1/phone/*
├── openapi/                  # OpenAPI schema additions
└── manufacturing/            # reuse provider policy/auth patterns where applicable

apps/web/app/components/
└── FullSaasScreen.tsx        # initial admin/operator screens, if this feature lands in current shell

packages/shared/src/dto/
└── phone.ts                  # shared DTOs for call/session/scenario/handoff/metrics

tests/
├── unit/test_phone_*.py
├── contract/test_phone_openapi.py
├── security/test_phone_tenant_acl.py
└── integration/test_phone_call_flow.py

apps/api/test/
└── phone.e2e-spec.ts
```

**Structure Decision**: Add a new Python `phone` solution layer that composes existing `AnswerService`/manufacturing safety concepts rather than embedding phone logic into generic RAG services. Expose the feature through the existing NestJS API facade and shared DTO package. Keep deterministic provider fakes local and make production telephony/ASR/TTS adapters configuration-gated.

## Phase 0 Research Plan

1. Decide local MVP provider model:
   - deterministic call simulator
   - transcript-in/text-out fake ASR/TTS
   - later adapters for SIP/PBX/Amazon Connect/etc.
2. Decide conversation orchestrator boundaries:
   - when to call RAG
   - when to ask clarification
   - when to hand off
   - how scenario state is represented
3. Decide handoff package shape and operator workflow.
4. Decide call history retention/redaction model.
5. Decide which existing RAG/admin screens can be reused and which phone-specific screens are needed.

## Phase 1 Design Outputs

- [research.md](research.md): provider, orchestration, handoff, compliance, and reuse decisions.
- [data-model.md](data-model.md): CallSession, ConversationTurn, Scenario, HandoffPackage, QualityEvaluation, metrics.
- [contracts/phone-rag-openapi.md](contracts/phone-rag-openapi.md): public API and internal facade contracts.
- [quickstart.md](quickstart.md): local deterministic demo and acceptance smoke.

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| AI gives unsupported spoken answer | Customer harm, legal/commercial risk | Groundedness gate + insufficient evidence handoff + call probes |
| Caller PII/audio leaks | Compliance/security risk | Redaction, retention, tenant ACL, provider policy, audit |
| Handoff lacks context | Poor CX; repeated explanation | Mandatory handoff package and operator acceptance tests |
| Provider outage creates silence | Call failure | fail-closed fallback messages, IVR/human/callback fallback |
| Scenario drift causes bad behavior | Operational risk | versioning, approval, simulation, rollback |
| Tier A becomes slow/cloud-dependent | Developer loop breaks | deterministic providers in Tier A; live provider tests only outer tiers/human-gated |

## Complexity Tracking

No constitution violations are currently planned. The feature is large, but complexity is kept behind provider interfaces and incremental MVP slices.
