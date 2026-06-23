# Tasks: Manufacturing Workspace — usable

**Input**: `spec.md`, `plan.md` in `/specs/014-manufacturing-workspace-usable/`

**Tests**: TypeScript typecheck/build, NestJS API e2e, Tier A (`scripts/gate.sh a`), full suite.

**Implementation status**: Completed locally across `bc7ff51` (slice 1), `ab1d0b7` (slice 2),
`644dc8a` (slice 3), with follow-up fixes in `92c981b` and `4ea09bb`. Re-verified 2026-06-22 with
`npm run build:shared`, `npm run typecheck`, `npm run build --workspace @raku-rag/web`,
`npm run test:api`, and `scripts/gate.sh a`.

## Phase 1: Foundation + Operations (slice 1)

- [x] T001 Add shared DTOs in `packages/shared/src/dto/manufacturing.ts` (dashboard, safety-telemetry,
  KPI, governance) + re-export from the package index.
- [x] T002 Add `lib/session.ts` (`getSessionToken()` — mint once, cache in module + sessionStorage).
- [x] T003 Extend `lib/api-client.ts` with `mfgGet`/typed helpers: `manufacturingDashboard`,
  `manufacturingSafetyTelemetry`, `manufacturingKpi`, `manufacturingGovernanceStatus`.
- [x] T004 Extract the app-shell: shared `Sidebar` client component (`usePathname` active state,
  `next/link`) + move shell into `app/layout.tsx`; reduce `app/page.tsx` to the Answers content.
- [x] T005 Build `app/operations/page.tsx` rendering dashboard + safety-telemetry + KPI + governance
  with explicit zero/empty states and capped lists.
- [x] T006 Styles for nav-active + operations panels in `app/globals.css`.
- [x] T007 Verify: typecheck (all), web build, API e2e, Tier A; commit locally.

## Phase 2: Sources (slice 2)

- [x] T008 DTOs + client helpers: trouble-case search, source sync-status, ingestion-run.
- [x] T009 `app/sources/page.tsx`: trouble-case search (candidates/reference), source sync-status +
  ingestion-run lookup, approval/freshness labels.
- [x] T010 Verify + commit locally.

## Phase 3: Reviews (slice 3)

- [x] T011 DTOs + client helpers: get draft, create draft, assign draft, review draft, document approval.
- [x] T012 `app/reviews/page.tsx`: draft inspect/state-machine + assign/review/approval as explicit
  human actions; surface server authorization outcomes; AI output labeled `draft`.
- [x] T013 Verify (incl. SC-005: draft never shown approved; rejected mutation leaves state unchanged)
  + commit locally.
