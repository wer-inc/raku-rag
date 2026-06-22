# Tasks: Manufacturing Workspace — usable

**Input**: `spec.md`, `plan.md` in `/specs/014-manufacturing-workspace-usable/`

**Tests**: TypeScript typecheck/build, NestJS API e2e, Tier A (`scripts/gate.sh a`), full suite.

## Phase 1: Foundation + Operations (slice 1)

- [ ] T001 Add shared DTOs in `packages/shared/src/dto/manufacturing.ts` (dashboard, safety-telemetry,
  KPI, governance) + re-export from the package index.
- [ ] T002 Add `lib/session.ts` (`getSessionToken()` — mint once, cache in module + sessionStorage).
- [ ] T003 Extend `lib/api-client.ts` with `mfgGet`/typed helpers: `manufacturingDashboard`,
  `manufacturingSafetyTelemetry`, `manufacturingKpi`, `manufacturingGovernanceStatus`.
- [ ] T004 Extract the app-shell: shared `Sidebar` client component (`usePathname` active state,
  `next/link`) + move shell into `app/layout.tsx`; reduce `app/page.tsx` to the Answers content.
- [ ] T005 Build `app/operations/page.tsx` rendering dashboard + safety-telemetry + KPI + governance
  with explicit zero/empty states and capped lists.
- [ ] T006 Styles for nav-active + operations panels in `app/globals.css`.
- [ ] T007 Verify: typecheck (all), web build, API e2e, Tier A; commit locally.

## Phase 2: Sources (slice 2)

- [ ] T008 DTOs + client helpers: trouble-case search, source sync-status, ingestion-run.
- [ ] T009 `app/sources/page.tsx`: trouble-case search (candidates/reference), source sync-status +
  ingestion-run lookup, approval/freshness labels.
- [ ] T010 Verify + commit locally.

## Phase 3: Reviews (slice 3)

- [ ] T011 DTOs + client helpers: get draft, create draft, assign draft, review draft, document approval.
- [ ] T012 `app/reviews/page.tsx`: draft inspect/state-machine + assign/review/approval as explicit
  human actions; surface server authorization outcomes; AI output labeled `draft`.
- [ ] T013 Verify (incl. SC-005: draft never shown approved; rejected mutation leaves state unchanged)
  + commit locally.
