# Feature Specification: Manufacturing Workspace — usable

**Feature Branch**: `014-manufacturing-workspace-usable` (developed locally on the `013` stack)

**Created**: 2026-06-22

**Status**: Draft

**Input**: Follow-up to `013` (Manufacturing Answer Workspace PoC v0). The PoC wired the answer path
to `/v1/manufacturing/answer`, but the workspace nav (`Sources`, `Reviews`, `Operations`) is dead
placeholder text and the app is single-shot Q&A. The manufacturing backend already exposes ~20
endpoints (dashboard, KPI, safety-telemetry, governance, audit export, drafts review, document
approval, source sync, trouble-case search) via the NestJS facade → answer-service →
`manufacturing_system`; they are implemented and covered by backend + API e2e tests. This feature
makes the existing backend value **actually usable** from the workspace, locally, without changing
the safety core.

## Overview

Turn the single-page answer demo into a navigable manufacturing knowledge workspace whose four
sections each expose an already-implemented backend capability:

- **Answers** (from `013`): ask a grounded question; see answer/evidence-gap, high-risk safety
  state, and citation approval/freshness provenance.
- **Operations**: a read-only knowledge-ops view — unanswered/low-rating/frequent/obsolete/
  knowledge-gap dashboard, safety-telemetry (high-risk + safety-gate block breakdown), the PoC KPI
  set, and governance status.
- **Sources**: search past trouble-cases (shown as candidates/reference), inspect source sync-status,
  and look up ingestion-run status with approval/freshness labels where the backend returns them.
- **Reviews**: the human review loop — open or create AI-authored drafts by artifact id, assign and
  review/decide them, and set document approval state. AI outputs stay `draft`; a human decides.

This is intentionally NOT a full DMS / e-signature / arbitrary-rollback console (out of scope per
`002`). It is the smallest navigable surface that lets a field user, a reviewer, and an ops owner
each do their job against the existing safety overlay.

Constitution fit:

- **I Groundedness First**: blocked / insufficient-evidence / draft / candidate states are shown as
  such; no UI copy implies a safe instruction or an approved fact where the backend did not assert one.
- **II Traceability**: dashboard/telemetry/KPI values are read straight from the audit-derived
  backend views; the UI adds no parallel counter and relabels nothing.
- **III Security by Design**: tenant/user always come from the signed dev-token via the API facade;
  browser code never sends tenant/identity overrides. Admin mutations are gated server-side
  (`assertAdminMutationAllowed`); the UI surfaces the server's authorization result, it does not grant.
- **VI Human Safety Boundary** (`002` hard rule + loop-engineering §6): draft approval, high-risk
  assertion, and audit remain backend-enforced and human-decided. The UI initiates a human's decision;
  it never auto-approves and never weakens a gate.
- **VII API First**: every view consumes the existing `/v1/manufacturing/*` contract through shared
  DTOs; no UI-only shapes are invented.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Navigate between workspace sections (Priority: P1)

As any workspace user, I can move between Answers, Operations, Sources, and Reviews, and the app shows
me which section I am in.

**Why this priority**: Without real routing the backend value is unreachable; the nav is the spine of
"usable".

**Independent Test**: Web build emits the four routes; the nav highlights the active route from the URL.

**Acceptance Scenarios**:

1. **Given** the workspace, **When** I click `Operations`, **Then** the URL is `/operations` and the
   Operations view renders with the nav item marked active.
2. **Given** I deep-link to `/sources`, **When** the page loads, **Then** the Sources view renders
   inside the shared app-shell (sidebar + topbar) without a full reimplementation per page.

---

### User Story 2 - See knowledge-ops health (Operations) (Priority: P1)

As an ops owner, I can see what the knowledge base is failing at: unanswered/blocked questions,
low-rating answers, frequently-referenced and obsolete documents, knowledge-gap areas, high-risk
volume, and where the safety gate is blocking.

**Why this priority**: This is the manufacturing differentiator made observable; it needs no schema
change and no mutation.

**Independent Test**: Web typecheck/build renders the dashboard + safety-telemetry + KPI + governance
payloads defensively (empty/zero states included).

**Acceptance Scenarios**:

1. **Given** an empty/cold tenant, **When** Operations loads, **Then** every panel renders its
   zero/empty state without crashing (no audit activity yet).
2. **Given** prior answer activity, **When** Operations loads, **Then** `unanswered_question_count`,
   `safety_gate_block_count`, the block breakdown, and the obsolete-candidate / knowledge-gap lists
   reflect the audit-derived backend values.
3. **Given** a cross-tenant principal, **When** Operations loads, **Then** the views are empty (the
   backend scopes by signed tenant; the UI never widens it).

---

### User Story 3 - Search sources and past cases (Sources) (Priority: P2)

As a field user or reviewer, I can search prior trouble-cases as reference candidates and check a
known source's sync / ingestion-run status, including approval and freshness labels when the backend
returns them.

**Why this priority**: Trust in an answer requires inspecting the underlying source state without
inventing a broader source-list endpoint.

**Independent Test**: Web build renders source/approval/freshness labels and the trouble-case results
list; missing optional fields degrade gracefully.

**Acceptance Scenarios**:

1. **Given** a trouble-case query, **When** I search, **Then** results render as **candidates /
   reference** (never as an approved instruction), matching the backend's past-case semantics.
2. **Given** a source id or ingestion-run id, **When** I look it up, **Then** the latest known state is
   shown; an obsolete/draft source is labeled reference-only when that approval state is present.

---

### User Story 4 - Run the human review loop (Reviews) (Priority: P2)

As a reviewer, I can open or create an AI-authored draft, assign it, record a review decision, and set
a document's approval state — all as explicit human actions.

**Why this priority**: AI outputs are always `draft`; the product's safety value is the human deciding.
The backend enforces this; the UI must make it doable.

**Independent Test**: API e2e already pins the draft/approval pass-through; Web build renders the draft
state machine and disables actions the server reports as unauthorized.

**Acceptance Scenarios**:

1. **Given** an AI-authored draft, **When** I view it, **Then** it is labeled `draft` and shows its
   review state; the UI never presents it as approved knowledge.
2. **Given** I am authorized, **When** I record a review decision or document approval, **Then** the
   request carries my signed identity, the backend audits the transition, and the UI reflects the
   returned state.
3. **Given** I am not authorized, **When** I attempt a mutation, **Then** the server rejects it and the
   UI shows the rejection without having changed any state.

### Edge Cases

- An older API without a given view returns 404/empty: the section shows an empty state, not a crash.
- A read view returns large lists: the UI caps the rendered rows and says so (no silent truncation).
- A mutation fails mid-flight: the UI surfaces the error and re-reads state rather than assuming success.
- The dev-token issuer is disabled (e.g. `NODE_ENV=production`): the app shows the auth-unavailable
  state instead of calling protected endpoints with no token.

## Requirements *(mandatory)*

- **FR-001**: The workspace MUST provide real routes for Answers (`/`), Operations (`/operations`),
  Sources (`/sources`), and Reviews (`/reviews`) inside a shared app-shell, with the active route
  indicated from the URL.
- **FR-002**: The Operations view MUST render the knowledge-ops dashboard, safety-telemetry, KPI, and
  governance-status payloads from `/v1/manufacturing/{dashboard,safety-telemetry,kpi,governance/status}`
  through shared DTOs, including zero/empty states.
- **FR-003**: The Sources view MUST surface trouble-case search results as candidates/reference and
  source sync-status / ingestion-run lookup results, with approval/freshness labels when provided.
- **FR-004**: The Reviews view MUST open/inspect or create drafts and initiate assign / review /
  document-approval mutations as explicit human actions, labeling AI outputs as `draft` and never as
  approved.
- **FR-005**: All requests MUST authenticate via the signed dev-token through the API facade; the
  browser MUST NOT add tenant/user identity to request bodies, and MUST NOT widen tenant scope.
- **FR-006**: The UI MUST NOT change any safety decision: it renders backend safety/approval/governance
  results and surfaces server-reported authorization outcomes; it never auto-approves or
  locally overrides a gate.
- **FR-007**: The shared TypeScript contract MUST define DTOs for the dashboard, safety-telemetry, KPI,
  governance, trouble-case, source-status, and draft/approval payloads consumed by the views.
- **FR-008**: The dev-token session MUST be minted once and reused across views (no re-mint per request).

### Key Entities

- **KnowledgeOpsDashboard**: `unanswered_question_count`, `low_rating_answers[]`, `frequent_questions[]`,
  `frequently_referenced_documents[]`, `obsolete_document_candidates[]`, `knowledge_gap_areas[]`,
  `correlation_id`.
- **SafetyTelemetryView**: `tenant_id`, `high_risk_query_count`, `safety_gate_block_count`,
  `block_breakdown` / `safety_gate_block_breakdown`, `axis`, `time_range`, `source`, `correlation_id`.
- **ManufacturingKpi**: the PoC KPI key/value set (json) + provenance (`source`, `materialized_at`).
- **GovernanceStatus**: policy/retention/no-train governance summary.
- **TroubleCaseCandidate**: a past case shown as a reference candidate (id, summary, score, state).
- **SourceSyncStatus / IngestionRun**: source freshness + last ingestion-run state.
- **DraftArtifact**: AI-authored draft with `draft` state, review/assignment state, provenance.

## Success Criteria *(mandatory)*

- **SC-001**: `npm --prefix apps/web run typecheck` and `npm --prefix apps/web run build` are green.
- **SC-002**: `npm --prefix apps/api run typecheck` and manufacturing/API e2e tests are green.
- **SC-003**: Each of the four sections renders its empty/zero state without crashing on a cold tenant.
- **SC-004**: No safety regression — Tier A (`scripts/gate.sh a`) GREEN; the full suite green; the
  generic `/v1/answer` and existing manufacturing contracts remain backward-compatible.
- **SC-005**: A draft/candidate is never rendered as approved knowledge; a server-rejected mutation
  leaves UI state unchanged.

## Assumptions

- Backend correctness (high-risk gate, approval/audit, governance, KPI derivation) is already covered
  by manufacturing + answer-service tests; this feature only exposes the existing paths in the frontend.
- Streaming, real-time refresh, pagination beyond a capped first page, and CSV download UX are deferred.
- This is developed and verified **locally** on the `013` foundation stack; push/PR/merge to
  `origin/002` is a separate decision (the stack is not yet on the remote).
- No backend route or safety-logic change is required; if a view needs data no endpoint provides, it is
  cut from scope rather than added to the safety core in this feature.
