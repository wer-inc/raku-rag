<!-- SPECKIT START -->
## Active Feature: 002-manufacturing-field-knowledge-rag (Solution Layer — tasks generated, ready for /speckit-implement)

Manufacturing Field Knowledge RAG built **on top of** the 001 base platform (do NOT redefine base
features — reference them). Plan & design artifacts complete (GQ1=block, GQ2=customer 1yr/audit 1yr
resolved). `tasks.md` is generated (71 tasks T001–T072 across 10 phases); next step is `/speckit-analyze` (preflight) → `/speckit-implement`.

- Plan: `specs/002-manufacturing-field-knowledge-rag/plan.md` · Research: `specs/002-manufacturing-field-knowledge-rag/research.md`
- Data model: `specs/002-manufacturing-field-knowledge-rag/data-model.md` · Contracts: `specs/002-manufacturing-field-knowledge-rag/contracts/` (mfg-openapi.md, mfg-interfaces.md)
- Quickstart: `specs/002-manufacturing-field-knowledge-rag/quickstart.md` · Spec: `specs/002-manufacturing-field-knowledge-rag/spec.md`
- Checklist: `specs/002-manufacturing-field-knowledge-rag/checklists/requirements.md`

Solution-layer hard rules: AI outputs are always `draft` (human review required); safety/quality/
equipment-operation (high-risk) answers require an approved+effective citation or no assertion;
draft/obsolete docs are reference-only (obsolete needs a warning); past-case countermeasures are
shown as candidates/reference; approval state + reviewer + evidence + state transitions are audited;
full DMS / e-signature / arbitrary rollback are out of scope.

## Base Platform: 001-rag-platform (Generic RAG Platform — MVP core implemented & tested)

Reuse (do not redefine): multi-tenant isolation, ACL deny-by-default pre-filter, signed-token auth,
citation/groundedness, ingestion/search/answer/deletion (tombstone), evaluation/cost/observability,
visual RAG (OCR/visual citation, captioning optional).

- Plan: `specs/001-rag-platform/plan.md` · Research: `specs/001-rag-platform/research.md`
- Data model: `specs/001-rag-platform/data-model.md` · Contracts: `specs/001-rag-platform/contracts/`
- Quickstart: `specs/001-rag-platform/quickstart.md` · Spec: `specs/001-rag-platform/spec.md`
- Constitution: `.specify/memory/constitution.md`

Stack (per plan.md / ADR-002): NestJS (sync API) + Next.js (Vercel AI SDK client) + Python 3.12
worker (parser/OCR/embedding/eval) + PostgreSQL/pgvector + S3-compatible storage + SQS+DLQ. Arq/Redis
is a local/dev-only queue adapter, not the production queue. Components abstracted behind the shared
contracts / `src/raku_rag/interfaces/`. MVP core (tenancy/ACL/ingestion/search/answer/citation/
groundedness/deletion) is implemented stdlib-only under `src/raku_rag/` and verified by `tests/`
(security hard gates pass). Production adapters (NestJS API / pgvector / SQS worker) are pending.
Top risks: ACL leakage and deleted-content reappearance — enforced via ACL pre-filter and tombstone.
<!-- SPECKIT END -->

## Loop Engineering (how this project is driven)

Driven via loop engineering — see `docs/loop-engineering.md` (SSOT). Verification gate:
`scripts/gate.sh` (Tier A hard gates, ~3ms, stdlib). Track A = stdlib-first to keep the gate fast.
Supervised (~1–2h/day); phased driver automation — non-safety loops self-drive, the safety boundary
(hard-gate design, draft approval, high-risk assertion, no-train, audit) is always human.
