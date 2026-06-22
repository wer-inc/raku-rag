# Implementation Plan: Manufacturing Workspace — usable

**Branch**: `014-manufacturing-workspace-usable` (local, on the `013` stack) · **Spec**: `./spec.md`

## Technical Context

- **Frontend**: Next.js 14 App Router (`apps/web`), React 18, TypeScript. Existing single page
  `app/page.tsx` (Answers) + minimal `app/layout.tsx` + `lib/api-client.ts` + `app/globals.css`.
- **Contract**: shared DTOs in `packages/shared/src/dto/`. API facade `apps/api` (NestJS) already
  exposes the full `/v1/manufacturing/*` surface; answer-service implements the `/internal/*` routes.
- **Auth**: dev-token route `app/api/dev-token/route.ts` (HMAC) → `x-user-token` + `Bearer local-dev-key`.
- **No backend change** is planned; this is frontend + shared-DTO work. If a view needs data no endpoint
  provides, the view is cut, not the safety core extended (see spec Assumptions).

## Constitution Check

- Groundedness/Traceability/Security/API-First/Human-Safety per spec "Constitution fit". The only code
  that runs server-side is the existing, tested facade; new code is browser-side rendering + typed
  client calls. PASS (no gate touched).

## Architecture

- **App-shell**: extract the sidebar + topbar shell out of `page.tsx` into `app/layout.tsx` (server)
  + a small `app/(components)/Sidebar.tsx` client component using `usePathname()` for active state and
  `next/link` for navigation. Each route renders only its section content.
- **Session**: `lib/session.ts` — `getSessionToken()` mints the dev-token once (module-cached +
  `sessionStorage`) and reuses it; pages call it before fetching. Replaces per-ask minting in `page.tsx`.
- **Client**: extend `lib/api-client.ts` with typed GET/POST helpers for the manufacturing views
  (a shared `mfgGet`/`mfgPost` adding the auth headers). 
- **DTOs**: `packages/shared/src/dto/manufacturing.ts` — dashboard, safety-telemetry, KPI, governance,
  trouble-case, source-status, draft/approval shapes; re-export from the package index.
- **Routes**: `/operations`, `/sources`, `/reviews` as `app/<section>/page.tsx` client components; `/`
  stays Answers. Defensive rendering: every optional field guarded, every list capped with a
  "showing N of M" note (no silent truncation).

## Phases (each an independently verified local commit)

- **Phase 1 — Foundation + Operations** (slice 1): app-shell + routing + session + client/DTOs +
  `/operations` (dashboard, safety-telemetry, KPI, governance). Verify SC-001..004.
- **Phase 2 — Sources** (slice 2): `/sources` (trouble-case search, source sync-status, ingestion-run,
  approval/freshness labels). Verify.
- **Phase 3 — Reviews** (slice 3): `/reviews` (drafts list/detail, assign, review decision, document
  approval) as explicit human actions; server-reported authorization surfaced. Verify SC-005.

## Verification (every phase)

`npm run build:shared` · `npm run typecheck` (all workspaces) · `npm run test:api` (e2e) ·
`npm run build --workspace @raku-rag/web` · `scripts/gate.sh a` (Tier A) · `git diff --check` ·
`detect-secrets`. Commit locally per phase; do **not** push (the `013` stack is not on `origin/002`).

## Risks

- **Concurrent-actor working tree**: commit only the explicit files; never `memo.txt`.
- **List endpoints**: some sections (drafts/sources) have read-by-id but no flat list; the view uses the
  dashboard/telemetry aggregates + id-driven lookups, and states clearly when a flat list is unavailable
  rather than inventing a backend list endpoint.
