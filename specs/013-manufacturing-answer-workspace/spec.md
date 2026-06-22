# Feature Specification: Manufacturing Answer Workspace PoC v0

**Feature Branch**: `013-manufacturing-answer-workspace`

**Created**: 2026-06-22

**Status**: Draft

**Input**: Frontend gap review: the Next.js workspace can ask `/v1/answer`, but it does not consume the manufacturing safety overlay that already exists on `/v1/manufacturing/answer`.

## Overview

Make the existing answer workspace demonstrate the manufacturing PoC v0 value: a field user asks a grounded question, sees the answer or evidence gap, sees high-risk safety state, and can inspect citation approval/freshness provenance. This is intentionally not a full admin console; it is the smallest UI slice that exposes the safety overlay already implemented in the backend.

Constitution fit:

- **I Groundedness First**: blocked or insufficient-evidence answers must be shown as such, without UI copy implying a safe instruction was produced.
- **II Traceability**: citations must keep `source_id`, `document_id`, `chunk_id`, `version`, `retrieval_score`, plus manufacturing approval provenance where present.
- **III Security by Design**: tenant/user still come from the signed token and API facade; browser code never sends tenant overrides.
- **VII API First**: Web consumes `/v1/manufacturing/answer` through shared DTOs instead of inventing a UI-only shape.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask through the manufacturing answer path (Priority: P1)

As a manufacturing operator, I ask a question from the answer workspace and the request goes through the manufacturing safety overlay, not the generic answer path.

**Why this priority**: Without this, the UI bypasses the domain-specific safety value even though the backend has it.

**Independent Test**: TypeScript contract/build confirms the Web client calls `/manufacturing/answer` and consumes `ManufacturingAnswerResponse`; API e2e pins the schema and pass-through.

**Acceptance Scenarios**:

1. **Given** a signed local-dev user token, **When** the Web client submits a question, **Then** the request is sent to `/v1/manufacturing/answer`.
2. **Given** the API returns `manufacturing.high_risk=true`, **When** the UI renders the result, **Then** the answer panel shows the high-risk state and does not hide the `safety_block_reason`.

---

### User Story 2 - Show safety and evidence state in the answer panel (Priority: P1)

As a field user, I can tell whether the answer is safe to act on, blocked for approved evidence, or requires on-site confirmation.

**Why this priority**: This is the manufacturing PoC v0 differentiator; answer text alone is not enough for high-risk operations.

**Independent Test**: Web typecheck/build validates all safety fields are typed and rendered without optional-field crashes.

**Acceptance Scenarios**:

1. **Given** `safety_block_reason=approved_citation_missing`, **When** the result renders, **Then** the UI displays the block reason.
2. **Given** `requires_onsite_confirmation=true`, **When** the result renders, **Then** the UI displays a field-confirmation notice.
3. **Given** `obsolete_warning=true`, **When** the result renders, **Then** the UI displays an obsolete-source warning.

---

### User Story 3 - Show citation approval provenance (Priority: P2)

As a reviewer, I can inspect whether each cited source was approved, effective, and traceable.

**Why this priority**: It closes the visible gap between backend citation enforcement and UI trust.

**Independent Test**: TypeScript contract includes optional manufacturing citation fields and the Web build renders them defensively.

**Acceptance Scenarios**:

1. **Given** a citation with `approval_status`, **When** citations render, **Then** the status appears as a label.
2. **Given** a citation with `effective_date`, **When** citations render, **Then** the date appears with the source metadata.
3. **Given** a generic citation without manufacturing fields, **When** citations render, **Then** the UI still renders the base citation identifiers.

### Edge Cases

- Manufacturing response lacks optional `manufacturing` because an older API is running: the UI still renders the base answer and citations.
- Citation lacks `approval_status` or `effective_date`: the UI omits only that label, not the whole citation.
- Answer is blocked with `text=null`: the UI shows the empty-answer state plus safety reason.
- API failure or answer-service outage: existing error panel remains the only surfaced failure state.

## Requirements *(mandatory)*

- **FR-001**: The shared TypeScript contract MUST define `ManufacturingAnswerRequest`, `ManufacturingSafetyExtension`, `ManufacturingAnswerResponse`, and manufacturing citation provenance fields.
- **FR-002**: The Web client MUST call `/v1/manufacturing/answer` for the answer workspace.
- **FR-003**: The answer workspace MUST display `high_risk`, `safety_block_reason`, `obsolete_warning`, `requires_onsite_confirmation`, and `notice` when provided.
- **FR-004**: The citation list MUST display `approval_status`, `effective_date`, and `approval_source` when provided.
- **FR-005**: The UI MUST preserve the signed-token auth path and MUST NOT add tenant/user identity to the request body.
- **FR-006**: The API OpenAPI schema MUST expose the manufacturing answer fields so API-first consumers can rely on the same contract.

### Key Entities

- **ManufacturingAnswerRequest**: `query`, optional `collection_id`, optional `intent_hint`, optional `manufacturing_filters`.
- **ManufacturingAnswerResponse**: base answer response plus `manufacturing`.
- **ManufacturingSafetyExtension**: high-risk classification and safety display fields.
- **Citation approval provenance**: optional `approval_status`, `effective_date`, `approval_source`.

## Success Criteria *(mandatory)*

- **SC-001**: `npm --prefix apps/web run typecheck` and `npm --prefix apps/web run build` are green.
- **SC-002**: `npm --prefix apps/api run typecheck` and manufacturing/API e2e tests are green.
- **SC-003**: The UI can render a high-risk blocked response without crashing and without implying an actionable answer exists.
- **SC-004**: The generic `/v1/answer` contract remains backward-compatible.

## Assumptions

- Streaming remains out of scope for PoC v0.
- Review/draft workflows, dashboard/KPI, audit explorer, and policy management remain follow-up UI slices.
- Backend safety correctness is already covered by manufacturing and answer-service tests; this feature only exposes the existing path in the frontend.
