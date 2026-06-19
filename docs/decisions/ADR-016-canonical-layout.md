# ADR-016: Canonical Monorepo Layout (Phase 0 P0-T01)

Status: Accepted (2026-06-19)

Resolves the `src/raku_rag` ↔ `workers/ingest` path duality flagged in tasks.md Path Conventions,
plan.md L558, and the Phase 0/1 re-analyze (F8 / TR-06). Every later Phase 0/1 task pins file paths
to this ADR.

## Decision

### Package manager
- **npm workspaces** (npm ≥ 10) for the JS/TS side. `pnpm`/`yarn` are NOT required (not assumed
  present). Root `package.json` declares `workspaces: ["apps/*", "packages/*"]`.
- **Python**: a single package `raku_rag` rooted at `src/`, plus a worker runtime host at
  `workers/ingest/`. Dependency/config via the existing root `pyproject.toml`.

### Directory layout
```
apps/
  api/          NestJS sync API (TypeScript)            — P0-T05/T06
  web/          Next.js + Vercel AI SDK client          — P0-T07/T08
workers/
  ingest/       Python worker RUNTIME host (entrypoint, queue consumer);
                imports raku_rag — NOT a second copy    — P0-T03
packages/
  shared/       TypeScript contracts (DTOs + policy types w/ ADR-015 lifecycle fields) — P0-T04
src/
  raku_rag/     CANONICAL Python package (core/domain/interfaces/observability/providers/
                services + Phase 0 additions: migrations/, seed/, providers/mock/)
infra/
  db/           docker-compose Postgres+pgvector init + migrations dir      — P0-T13/T18
  localstack/   SQS dev queue + DLQ bootstrap                               — P0-T14
  langfuse/     local trace-sink compose config                            — P0-T14
docs/decisions/ ADRs (this file)
tests/          Python tests: unit/ contract/ integration/ security/       — P0-T15/T19/T21
.github/workflows/  CI                                                     — P0-T16
```

### Path-duality resolution (amends decompose "relocate")
The decomposition (P0-3) proposed **relocating** `src/raku_rag` under `workers/ingest`. We instead
**host, do not move**:

- The Python package `raku_rag` **stays at `src/raku_rag`** (canonical, unchanged import path).
- `workers/ingest/` is the worker **runtime entrypoint** that imports `raku_rag`; it is not a copy.

Rationale: the existing stdlib core under `src/raku_rag` has **passing security hard-gate tests**
(ACL leak, tenant isolation, deletion reappearance). A physical move would churn imports and risk
those gates for zero functional gain. The "single Python package" requirement is satisfied by having
exactly one `raku_rag` package; the worker is its host. `tests/` continues to run with
`PYTHONPATH=src` (and an editable install `pip install -e .` resolves the same package).

### Conventions
- Python source root = `src/`. Run tests: `PYTHONPATH=src python3 -m unittest discover -s tests`.
- TS abstractions/contracts live in `packages/shared`; `apps/api` and `apps/web` consume it as a
  workspace dependency `@raku-rag/shared`.
- A Phase 0/1 task whose backlog map (`→Txxx`) names a NestJS path (e.g. `apps/api/...`) but whose
  Phase 0/1 runnable logic lives in the Python core targets BOTH: the Python core is the runnable
  source of truth in Phase 0/1; the NestJS surface is the production mirror (wired in later phases).
- Target Python is 3.12 (per plan.md); code stays 3.11+ compatible (CI/sandbox may run 3.11).

## Consequences
- No breaking move of `src/raku_rag`; existing tests stay green.
- New Phase 0 Python code (migration runner, seed loader, mock providers) lands under `src/raku_rag/`.
- New TS scaffolds (api/web/shared) are fresh skeletons under `apps/`/`packages/`.
- `infra/` owns all local-dependency config (compose, db init, localstack, langfuse).
