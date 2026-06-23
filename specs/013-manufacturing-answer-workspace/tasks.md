# Tasks: Manufacturing Answer Workspace PoC v0

**Input**: Design documents from `/specs/013-manufacturing-answer-workspace/`

**Prerequisites**: `spec.md`, `plan.md`, `contracts/manufacturing-answer-workspace.md`

**Tests**: TypeScript typecheck/build plus NestJS e2e contract checks.

## Phase 1: Contract

- [x] T001 Add manufacturing answer request/response DTOs and optional citation provenance to `packages/shared/src/dto/answer.ts`.
- [x] T002 Pin OpenAPI `Citation` provenance fields and `ManufacturingAnswerResponse` contract in `apps/api/src/openapi/openapi.controller.ts` and `apps/api/test/app.e2e-spec.ts`.
- [x] T003 Type the manufacturing facade response in `apps/api/src/manufacturing/manufacturing.controller.ts`.

## Phase 2: Web Workspace

- [x] T004 Add `manufacturingAnswer()` to `apps/web/lib/api-client.ts`.
- [x] T005 Switch `apps/web/app/page.tsx` to use `ManufacturingAnswerResponse` and `/v1/manufacturing/answer`.
- [x] T006 Render safety status, safety block reason, obsolete warning, on-site confirmation, and notice in `apps/web/app/page.tsx`.
- [x] T007 Render citation approval status, effective date, and approval source in `apps/web/app/page.tsx`.
- [x] T008 Add responsive styles for safety and provenance labels in `apps/web/app/globals.css`.

## Phase 3: Verification

- [x] T009 Run API typecheck and targeted e2e tests.
- [x] T010 Run Web typecheck and build.
