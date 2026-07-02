# Tasks: AI Phone RAG Contact Center

**Input**: Design documents from `/specs/022-ai-phone-rag/`

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/phone-rag-openapi.md`, `quickstart.md`

**Tests**: Included. The feature specification defines independently testable scenarios and safety criteria, so implementation tasks include contract, unit, security, integration, API e2e, and web checks.

**Skip rule**: If existing code already satisfies a task and the relevant tests prove it, mark the task complete without rewriting that code.

**Organization**: Tasks are grouped by phase and user story so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other tasks because it touches different files or has no direct dependency.
- **[Story]**: User story identifier from `spec.md`.
- Every task names the expected file path(s).

---

## Phase 1: Setup (Shared Structure)

**Purpose**: Create the feature surface without changing behavior.

- [x] T001 Create the phone package skeleton in `src/raku_rag/phone/__init__.py`, `src/raku_rag/phone/domain.py`, `src/raku_rag/phone/interfaces.py`, `src/raku_rag/phone/orchestrator.py`, `src/raku_rag/phone/scenarios.py`, `src/raku_rag/phone/handoff.py`, `src/raku_rag/phone/redaction.py`, `src/raku_rag/phone/quality.py`, and `src/raku_rag/phone/metrics.py`.
- [x] T002 [P] Create deterministic provider seam files in `src/raku_rag/providers/telephony.py`, `src/raku_rag/providers/asr.py`, and `src/raku_rag/providers/tts.py`.
- [x] T003 [P] Create persistence and repository placeholders in `src/raku_rag/persistence/phone_models.py`.
- [x] T004 [P] Create shared TypeScript DTO entry point in `packages/shared/src/dto/phone.ts` and export it from `packages/shared/src/index.ts`.
- [x] T005 [P] Create NestJS phone facade files in `apps/api/src/phone/phone.controller.ts` and `apps/api/src/phone/phone.service.ts`.
- [x] T006 [P] Create Postgres migration pair `infra/db/migrations/postgres/0016_phone_rag.sql` and `infra/db/migrations/postgres/0016_phone_rag.down.sql`. (Landed as `0017_phone_rag.sql` / `.down.sql` — 0016 was already taken by `0016_chatbot_source_exposure_policies` and migration numbering must stay contiguous.)
- [x] T007 [P] Create deterministic phone fixtures in `tests/fixtures/phone/faq_corpus.json`, `tests/fixtures/phone/scenarios.json`, and `tests/fixtures/phone/call_scripts.json`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the tenant-safe, deterministic phone foundation required by every user story.

**Critical**: No user story implementation should start until this phase is complete.

### Foundation Tests

- [x] T008 [P] Add domain/state-machine tests for call, turn, and scenario invariants in `tests/unit/test_phone_domain.py`.
- [x] T009 [P] Add redaction tests for phone numbers, card-like values, credentials, and auth headers in `tests/unit/test_phone_redaction.py`.
- [x] T010 [P] Add tenant/ACL isolation tests for phone retrieval, call history, handoff package, and transcript access in `tests/security/test_phone_tenant_acl.py`.
- [x] T011 [P] Add scenario version lifecycle tests for draft, approval, publish, immutability, and rollback in `tests/unit/test_phone_scenarios.py`.
- [x] T012 [P] Add OpenAPI contract coverage for `/v1/phone/*` routes in `tests/contract/test_phone_openapi.py`.

### Foundation Implementation

- [x] T013 Define `CallSession`, `ConversationTurn`, `PhoneCitationRef`, `CallScenario`, `ScenarioVersion`, `HandoffPackage`, `QualityEvaluation`, `CallMetricSnapshot`, and `ProviderConfig` domain models in `src/raku_rag/phone/domain.py`.
- [x] T014 Define `TelephonyProvider`, `AsrProvider`, `TtsProvider`, `HandoffProvider`, `ScenarioRepository`, `CallRepository`, and `PhoneAnswerGateway` interfaces in `src/raku_rag/phone/interfaces.py`.
- [x] T015 Implement deterministic in-memory repository behavior and Postgres mapping boundaries in `src/raku_rag/persistence/phone_models.py`.
- [x] T016 Implement PII/payment/secret redaction helpers in `src/raku_rag/phone/redaction.py` using existing observability redaction patterns from `src/raku_rag/observability/redaction.py`.
- [x] T017 Implement deterministic telephony, ASR, and TTS providers in `src/raku_rag/providers/telephony.py`, `src/raku_rag/providers/asr.py`, and `src/raku_rag/providers/tts.py`.
- [x] T018 Implement scenario validation defaults, required slot validation, submit-review/approval/publication/schedule/archive states, immutable published versions, and rollback helpers in `src/raku_rag/phone/scenarios.py`.
- [x] T019 Implement handoff package creation, destination selection, and outcome transitions in `src/raku_rag/phone/handoff.py`.
- [x] T020 Implement the conversation state machine skeleton in `src/raku_rag/phone/orchestrator.py`.
- [x] T021 Add internal answer-service route wiring for phone calls, turns, scenarios, QA, and metrics in `apps/answer-service/server.py`.
- [x] T022 Register `PhoneController` in `apps/api/src/app.module.ts` and protect it with `AuthMiddleware`.
- [x] T023 Define phone roles and role checks for `operator`, `ops_owner`, `qa_reviewer`, `scenario_admin`, `scenario_approver`, and privileged audit access in `apps/api/src/auth/roles.ts` and `apps/api/src/phone/phone.controller.ts`.
- [x] T024 Implement shared DTOs for calls, turns, scenarios, handoffs, QA, and metrics in `packages/shared/src/dto/phone.ts`.
- [x] T025 Apply tenant-scoped RLS tables, indexes, audit fields, and down migration cleanup in `infra/db/migrations/postgres/0016_phone_rag.sql` and `infra/db/migrations/postgres/0016_phone_rag.down.sql`. (Landed as `0017_phone_rag.sql` / `.down.sql`, see T006.)

**Checkpoint**: Deterministic providers, domain models, tenant-safe storage boundaries, API skeleton, and shared DTOs exist.

---

## Phase 3: User Story 1 - AIが電話を受け、根拠付きで回答する (Priority: P1)

**Goal**: Simulated inbound calls produce grounded AI answers with traceable citations, or avoid definitive answers when evidence is insufficient.

**Independent Test**: Start a simulated call, send an FAQ/business-hours utterance, verify `answer_with_citations`, TTS-ready text, `document_id` / `chunk_id` / `version` / `retrieval_score`, and fail-closed behavior for unsupported questions.

### Tests for User Story 1

- [x] T026 [P] [US1] Add orchestrator unit tests for grounded answer, insufficient evidence, stale/unapproved evidence, and barge-in behavior in `tests/unit/test_phone_orchestrator.py`.
- [x] T027 [P] [US1] Add integration test for deterministic FAQ call flow in `tests/integration/test_phone_call_flow.py`.
- [x] T028 [P] [US1] Add answer-service internal route tests for simulated calls and turns in `tests/integration/test_phone_answer_service.py`.
- [x] T029 [P] [US1] Add NestJS API e2e tests for `POST /v1/phone/calls/simulate` and `POST /v1/phone/calls/{call_id}/turns` in `apps/api/test/phone.e2e-spec.ts`.

### Implementation for User Story 1

- [x] T030 [US1] Implement call creation, call ID generation, correlation ID propagation, and initial state transitions in `src/raku_rag/phone/orchestrator.py`.
- [x] T031 [US1] Integrate the orchestrator with the existing answer/retrieval/groundedness path through `PhoneAnswerGateway` in `src/raku_rag/phone/orchestrator.py` and `src/raku_rag/services/answer.py`.
- [x] T032 [US1] Persist conversation turns, redacted transcript text, AI response text, action, latency, and citation references in `src/raku_rag/persistence/phone_models.py`.
- [x] T033 [US1] Implement barge-in and DTMF event normalization in `src/raku_rag/providers/telephony.py` and `src/raku_rag/phone/orchestrator.py`.
- [x] T034 [US1] Implement deterministic TTS text/audio references in `src/raku_rag/providers/tts.py`.
- [x] T035 [US1] Implement internal `POST /internal/phone/calls/simulate` and `POST /internal/phone/calls/{call_id}/turns` handlers in `apps/answer-service/server.py`.
- [x] T036 [US1] Implement public `POST /v1/phone/calls/simulate` and `POST /v1/phone/calls/{call_id}/turns` in `apps/api/src/phone/phone.controller.ts`.
- [x] T037 [US1] Add phone simulator request/response DTO use in `apps/api/src/phone/phone.service.ts` and `packages/shared/src/dto/phone.ts`.
- [x] T038 [US1] Add an initial phone simulator panel to `apps/web/app/components/FullSaasScreen.tsx` using `NEXT_PUBLIC_API_BASE`.

**Checkpoint**: User Story 1 is demoable with deterministic providers and traceable grounded answers.

---

## Phase 4: User Story 2 - 人間オペレーターへ適切に引き継ぐ (Priority: P1)

**Goal**: Customer-requested, unsafe, unsupported, angry, low-confidence, or high-risk calls create handoff packages and avoid AI overreach.

**Independent Test**: Send "人につないでください", insufficient-evidence, angry sentiment, and low-ASR-confidence turns; verify `handoff` action, reason, destination, package contents, and accept outcome.

### Tests for User Story 2

- [x] T039 [P] [US2] Add handoff rule unit tests for customer request, insufficient evidence, low ASR confidence, repeated misunderstanding, negative sentiment, high-risk intent, and provider failure in `tests/unit/test_phone_handoff.py`.
- [x] T040 [P] [US2] Add integration tests for handoff package creation and fail-closed fallback in `tests/integration/test_phone_handoff_flow.py`.
- [x] T041 [P] [US2] Add NestJS API e2e tests for `GET /v1/phone/handoffs/{handoff_package_id}` and `POST /v1/phone/handoffs/{handoff_package_id}/accept` in `apps/api/test/phone.e2e-spec.ts`.
- [x] T042 [P] [US2] Add security tests proving handoff packages expose only masked/redacted caller data by default in `tests/security/test_phone_handoff_redaction.py`.

### Implementation for User Story 2

- [x] T043 [US2] Implement handoff trigger evaluation in `src/raku_rag/phone/handoff.py`.
- [x] T044 [US2] Connect handoff decisions into turn execution in `src/raku_rag/phone/orchestrator.py`.
- [x] T045 [US2] Persist handoff package summary, transcript excerpt, confirmed slots, citations, reason, destination, status, and operator acceptance in `src/raku_rag/persistence/phone_models.py`.
- [x] T046 [US2] Implement live-transfer failure fallback states `queued`, `failed`, `unavailable`, `callback_requested`, and `abandoned` in `src/raku_rag/phone/handoff.py`.
- [x] T047 [US2] Implement internal answer-service handoff read/accept endpoints in `apps/answer-service/server.py`.
- [x] T048 [US2] Implement public handoff read/accept endpoints in `apps/api/src/phone/phone.controller.ts`.
- [x] T049 [US2] Add operator handoff queue and handoff detail UI to `apps/web/app/components/FullSaasScreen.tsx`.

**Checkpoint**: User Stories 1 and 2 both work independently and the AI transfers instead of forcing unsafe completion.

---

## Phase 5: User Story 3 - 管理者がナレッジとシナリオを運用する (Priority: P1)

**Goal**: Admins create, test, approve, publish, archive, and roll back phone scenarios without weakening existing knowledge approval and ACL behavior.

**Independent Test**: Create a scenario, configure required slots and handoff rules, preview a test conversation, publish it, run a call against it, then roll back and verify past calls keep their original `scenario_version_id`.

### Tests for User Story 3

- [x] T050 [P] [US3] Add scenario API e2e tests for list, create, update draft version, test preview, submit review, approve, publish, schedule, archive, and rollback in `apps/api/test/phone.e2e-spec.ts`.
- [x] T051 [P] [US3] Add scenario preview integration tests in `tests/integration/test_phone_scenario_preview.py`.
- [x] T052 [P] [US3] Add tests proving published scenario versions are immutable and past calls retain version references in `tests/unit/test_phone_scenarios.py`.
- [x] T053 [P] [US3] Add role tests for scenario admin versus scenario approver in `apps/api/test/phone.e2e-spec.ts`.

### Implementation for User Story 3

- [x] T054 [US3] Implement scenario create/list/update/test/submit-review/approve/publish/schedule/archive/rollback service methods in `src/raku_rag/phone/scenarios.py`.
- [x] T055 [US3] Persist `CallScenario` and `ScenarioVersion` records with immutable published payloads in `src/raku_rag/persistence/phone_models.py`.
- [x] T056 [US3] Ensure scenario publication requires a prior explicit approval action unless the caller has both approval and publish permissions in `src/raku_rag/phone/scenarios.py` and `apps/api/src/phone/phone.controller.ts`.
- [x] T057 [US3] Implement scenario preview execution through deterministic providers in `src/raku_rag/phone/orchestrator.py`.
- [x] T058 [US3] Implement internal scenario endpoints in `apps/answer-service/server.py`.
- [x] T059 [US3] Implement public scenario endpoints in `apps/api/src/phone/phone.controller.ts`.
- [x] T060 [US3] Add scenario DTOs and validation types in `packages/shared/src/dto/phone.ts`.
- [x] T061 [US3] Add scenario management, preview, publish, and rollback UI to `apps/web/app/components/FullSaasScreen.tsx`.
- [x] T062 [US3] Reuse existing datasource approval and document approval UI behavior for phone knowledge eligibility instead of creating a separate knowledge approval path in `apps/web/app/components/FullSaasScreen.tsx`.

**Checkpoint**: P1 technical demo is complete: phone answering, handoff, and scenario operations can be demonstrated end to end.

---

## Phase 6: User Story 4 - 応対履歴と品質を追跡する (Priority: P2)

**Goal**: Supervisors search call history, inspect redacted transcripts, citations, handoffs, recordings when permitted, and create QA reviews that feed improvement work.

**Independent Test**: Open a completed call, verify transcript/citations/handoff trace, submit a QA review with `hallucination_detected=true`, and verify an improvement item is created or linked.

### Tests for User Story 4

- [x] T063 [P] [US4] Add call history list/detail integration tests in `tests/integration/test_phone_call_history.py`.
- [x] T064 [P] [US4] Add QA evaluation and improvement item tests in `tests/integration/test_phone_quality_evaluation.py`.
- [x] T065 [P] [US4] Add audit coverage tests for transcript, recording, identifier, and QA access in `tests/security/test_phone_audit_access.py`. (Recording-audio access has no path yet — see T070 deferral; transcript/identifier/handoff/QA reads are audited.)
- [x] T066 [P] [US4] Add NestJS e2e tests for `GET /v1/phone/calls`, `GET /v1/phone/calls/{call_id}`, and `POST /v1/phone/calls/{call_id}/quality-evaluations` in `apps/api/test/phone.e2e-spec.ts`.
- [x] T067 [P] [US4] Add export, retention policy, and call deletion/redaction request tests in `tests/security/test_phone_data_lifecycle.py` and `apps/api/test/phone.e2e-spec.ts`.

### Implementation for User Story 4

- [x] T068 [US4] Implement call history search filters for call ID, date/time, customer ID, phone number, intent, result, handoff reason, and scenario. (Implemented in `PhoneCallService.list_calls` over the repository listing — one common path for the in-memory and Postgres repos — rather than per-repo SQL in `phone_models.py`.)
- [x] T069 [US4] Implement redacted call detail projection with transcript, AI responses, citations, handoff, scenario version, and correlation ID in `src/raku_rag/phone/orchestrator.py`.
- [ ] T070 [US4] Implement optional audio object reference access checks and audit logging in `src/raku_rag/persistence/phone_models.py` and `src/raku_rag/observability/audit.py`. (DEFERRED: the deterministic MVP stores no audio objects — `tts_audio_ref` is a synthetic URI and recording capture is 024 live-telephony scope. Transcript/identifier access auditing shipped under T065.)
- [x] T071 [US4] Implement quality evaluation creation and validation in `src/raku_rag/phone/quality.py`.
- [x] T072 [US4] Connect QA hallucination/knowledge-gap flags to the existing improvement workflow in `src/raku_rag/manufacturing/api/improvements.py` (audit-derived `phone_qa` items; no parallel store).
- [x] T073 [US4] Implement internal call history and QA endpoints in `apps/answer-service/server.py`.
- [x] T074 [US4] Implement public call history and QA endpoints in `apps/api/src/phone/phone.controller.ts`.
- [x] T075 [US4] Add call history, call detail, and QA review UI to `apps/web/app/components/FullSaasScreen.tsx` (通話履歴 tab).
- [x] T076 [US4] Implement redacted call/QA export request handling or explicit audited `export_not_enabled` responses in `apps/answer-service/server.py` and `apps/api/src/phone/phone.controller.ts` (409 + audit unless `RAKU_PHONE_EXPORT_ENABLED=1`).
- [x] T077 [US4] Implement retention policy read and call deletion/redaction request handling in `apps/answer-service/server.py`, `apps/api/src/phone/phone.controller.ts`, and `src/raku_rag/persistence/phone_models.py`. (Live-PG smoke caught and fixed a `save_handoff` upsert that dropped redacted summary/excerpt/slots on the Postgres path.)

**Checkpoint**: Supervisors can audit and improve phone AI behavior from persisted call evidence.

---

## Phase 7: User Story 5 - 運用KPIを可視化する (Priority: P2)

**Goal**: Operations owners can view call volume, AI containment, handoff rate, unresolved rate, top reasons/topics, and p95 latency from persisted call data.

**Independent Test**: Seed completed and handed-off calls, request metrics by day, and verify counts/rates/top reasons/latency match persisted data.

### Tests for User Story 5

- [x] T078 [P] [US5] Add KPI aggregation unit tests for call count, AI containment, handoff rate, unresolved rate, top reasons, and p95 latency in `tests/unit/test_phone_metrics.py`.
- [x] T079 [P] [US5] Add metrics endpoint integration tests in `tests/integration/test_phone_metrics_endpoint.py`.
- [x] T080 [P] [US5] Add NestJS e2e test for `GET /v1/phone/metrics` in `apps/api/test/phone.e2e-spec.ts`.

### Implementation for User Story 5

- [x] T081 [US5] Implement call metric aggregation in `src/raku_rag/phone/metrics.py`.
- [x] T082 [US5] Persist or compute `CallMetricSnapshot` records. (Computed on read from persisted calls + QA evaluations via `aggregate_call_metrics` — no snapshot table; the "or compute" branch.)
- [x] T083 [US5] Implement internal metrics endpoint in `apps/answer-service/server.py`.
- [x] T084 [US5] Implement public `GET /v1/phone/metrics` endpoint in `apps/api/src/phone/phone.controller.ts`.
- [x] T085 [US5] Add metrics DTOs in `packages/shared/src/dto/phone.ts`.
- [x] T086 [US5] Add phone operations KPI panel to `apps/web/app/components/FullSaasScreen.tsx` (KPI tab).

**Checkpoint**: P2 operations dashboard can be validated from deterministic seeded calls.

---

## Phase 8: Polish & Cross-Cutting Verification

**Purpose**: Final hardening, docs, and repository gates after the desired story slice is implemented.

- [x] T087 [P] Update `specs/022-ai-phone-rag/quickstart.md` if endpoint names, payloads, or commands changed during implementation.
- [ ] T088 [P] Update `docs/` with operator/admin workflow notes if the implemented UI changes terminology or approvals.
- [x] T089 [P] Add or update OpenAPI generated documentation coverage in `apps/api/src/openapi/openapi.controller.ts`.
- [x] T090 Run focused Python tests: `PYTHONPATH=src python3 -m unittest discover -s tests -t . -p 'test_phone_*.py' -q`.
- [x] T091 Run API tests: `npm run test:api`.
- [x] T092 Run shared/web TypeScript checks: `npm run build:shared` and `npm run typecheck --workspace @raku-rag/web`.
- [x] T093 Run Tier A gate: `scripts/gate.sh a`.
- [x] T094 Run full Python gate after the MVP slice is complete: `scripts/gate.sh all`.
- [x] T095 Run separation check if protected gate/test/security surfaces were edited: `scripts/gate.sh separation`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies.
- **Phase 2 Foundational**: Depends on Phase 1 and blocks all user stories.
- **Phase 3 US1**: Depends on Phase 2.
- **Phase 4 US2**: Depends on Phase 2 and can reuse call/session behavior from US1, but handoff rules remain independently testable.
- **Phase 5 US3**: Depends on Phase 2; may be developed in parallel with US1/US2 after the foundation is ready.
- **Phase 6 US4**: Depends on persisted call/turn/handoff data from US1/US2.
- **Phase 7 US5**: Depends on persisted call/turn/handoff/QA data from US1/US2/US4.
- **Phase 8 Polish**: Depends on the chosen implementation slice.

### MVP Delivery Order

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 (US1) and validate grounded phone answers.
3. Complete Phase 4 (US2) and validate safe handoff.
4. Complete Phase 5 (US3) and validate admin scenario operations.
5. Stop and demo the P1 technical demo before customer-facing MVP acceptance.
6. Complete minimum US4 call history, QA, export/retention/deletion controls.
7. Complete minimum US5 KPI dashboard.
8. Validate the product MVP slice from `goal.md`.

### Parallel Opportunities

- T002, T003, T004, T005, T006, and T007 can run in parallel after T001 starts.
- T008 through T012 can run in parallel as failing foundation tests.
- Provider implementation T017 can run in parallel with redaction T016, scenario T018, and handoff T019.
- US1 tests T026 through T029 can run in parallel.
- US2 tests T039 through T042 can run in parallel.
- US3 tests T050 through T053 can run in parallel.
- US4 tests T063 through T066 can run in parallel.
- Data lifecycle tests T067 can run after call history persistence exists.
- US5 tests T078 through T080 can run in parallel.
- Frontend tasks T038, T049, T061, T075, and T086 can be implemented after their corresponding DTO/API contracts stabilize.

### Notes

- Public API routes must derive tenant and user identity from signed auth context, never from request bodies.
- Live telephony, ASR, TTS, cloud, billed LLM, deployment, and production reindex/eval actions remain human-gated.
- Tier A must stay deterministic and must not require Docker, network, cloud, database, or heavy dependencies.
- Existing RAG retrieval, ACL, citations, groundedness, document approval, no-train, audit, and provider policy behavior should be reused rather than forked.
