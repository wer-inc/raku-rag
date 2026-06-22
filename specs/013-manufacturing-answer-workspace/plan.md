# Implementation Plan: Manufacturing Answer Workspace PoC v0

**Branch**: `013-manufacturing-answer-workspace` | **Date**: 2026-06-22 | **Spec**: `specs/013-manufacturing-answer-workspace/spec.md`

**Input**: Feature specification from `/specs/013-manufacturing-answer-workspace/spec.md`

## Summary

Expose the already-implemented manufacturing answer overlay in the Next.js workspace by adding shared DTOs, calling `/v1/manufacturing/answer`, rendering safety state and citation approval provenance, and pinning the API contract.

## Technical Context

**Language/Version**: TypeScript 5.5, Next.js 15.5, NestJS 11; Python answer-service already owns the safety overlay.

**Primary Dependencies**: `@raku-rag/shared`, Next.js app router, NestJS controllers/OpenAPI facade.

**Storage**: N/A for this UI slice.

**Testing**: TypeScript typecheck, Next.js build, NestJS e2e contract tests.

**Target Platform**: Web client plus NestJS v1 API facade.

**Project Type**: Web application consuming existing API.

**Performance Goals**: No added synchronous backend calls; same one answer request as before.

**Constraints**: Browser must not become a security boundary; tenant/user identity stays in signed token and API middleware.

**Scale/Scope**: One PoC v0 workspace screen, not the full manufacturing admin console.

## Constitution Check

- **I Groundedness First**: PASS. Blocked/insufficient answers remain visibly blocked; safety text is separate from answer text.
- **II Traceability**: PASS. Citation identifiers remain visible and gain approval provenance.
- **III Security by Design**: PASS. The Web body carries query/collection only; signed token remains identity source.
- **IV Pluggable Architecture**: PASS. UI consumes API DTOs; no retrieval/safety logic is duplicated.
- **V Evaluation-Gated Delivery**: PASS. Existing safety correctness tests remain in backend; this slice adds facade/type/build checks.
- **VI Observable by Default**: PASS. Correlation ID remains visible in the response panel.
- **VII API First**: PASS. Shared DTOs and OpenAPI schema are updated before UI consumption.
- **VIII Data Lifecycle Complete**: N/A. No data lifecycle mutation in this slice.

## Project Structure

```text
specs/013-manufacturing-answer-workspace/
├── spec.md
├── plan.md
├── tasks.md
└── contracts/
    └── manufacturing-answer-workspace.md

packages/shared/src/dto/answer.ts
apps/api/src/openapi/openapi.controller.ts
apps/api/test/app.e2e-spec.ts
apps/api/test/manufacturing.e2e-spec.ts
apps/web/lib/api-client.ts
apps/web/app/page.tsx
apps/web/app/globals.css
```

## Implementation Notes

- Keep `/v1/answer` backward-compatible by adding new manufacturing types rather than replacing `AnswerResponse`.
- Reuse the existing `/v1/manufacturing/answer` facade and upstream `/internal/manufacturing/answer`.
- Keep streaming out of scope; this is a contract and display slice.

## Verification

- `npm --prefix apps/api run typecheck`
- `npm --prefix apps/api run test:e2e -- --runTestsByPath test/app.e2e-spec.ts test/manufacturing.e2e-spec.ts --runInBand`
- `npm --prefix apps/web run typecheck`
- `npm --prefix apps/web run build`
