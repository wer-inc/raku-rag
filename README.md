# raku-rag — Generic RAG Platform (local-first monorepo)

Phase 0 establishes a **local-first foundation**: everyone can boot the same stack and run the
security/policy gates with deterministic mocks, no cloud credentials required. See
[`implementation-roadmap.md`](implementation-roadmap.md) and the Phase 0/1 Execution Plan in
[`specs/001-rag-platform/tasks.md`](specs/001-rag-platform/tasks.md).

## Layout (ADR-016)

```
apps/api/         NestJS sync API skeleton (/v1, mock auth)
apps/web/         Next.js + Vercel AI SDK client skeleton
workers/ingest/   Python worker runtime host (imports raku_rag)
packages/shared/  TypeScript contracts (DTOs + policy types, ADR-015 lifecycle fields)
src/raku_rag/     Canonical Python package (+ migrations/, seed/, providers/mock/)
infra/            docker-compose: postgres+pgvector, minio, localstack(sqs), langfuse(optional)
tests/            Python tests: unit / contract / integration / security
```

## Quickstart (Phase 0)

Prerequisites: Node ≥ 20 + npm, Python ≥ 3.11, Docker + docker compose.

```bash
# 1. env
cp .env.example .env

# 2. local dependencies (postgres+pgvector / minio / localstack)
docker compose -f infra/docker-compose.yml up -d
#   optional trace sink:  docker compose -f infra/docker-compose.yml --profile observability up -d

# 3. Python foundation (stdlib only — no install needed)
PYTHONPATH=src python3 -m unittest discover -s tests          # full suite (unit/integration/security)
PYTHONPATH=src python3 -m raku_rag.migrations.runner --dir infra/db/migrations --db .local/dev.sqlite
PYTHONPATH=src python3 workers/ingest/worker.py --smoke        # worker boots + wires mock providers

# 4. Node side
npm install
npm run build:shared          # packages/shared (tsc)
npm run dev:api               # NestJS API on http://localhost:3000/v1  (GET /v1/health)
npm run dev:web               # Next.js on  http://localhost:3002
npm run test:api              # NestJS e2e (health, /v1 versioning, mock auth)
```

### Verify
- `curl localhost:3000/v1/health` → `{"status":"ok",...}`
- `docker compose -f infra/docker-compose.yml exec postgres psql -U raku -d raku -c "SELECT extname FROM pg_extension WHERE extname='vector';"` → `vector`

## Scope

Phase 0 is the **foundation only** — no production data model, RLS, ACL pre-filter, real retrieval/
answer, real cloud providers, or industry verticals. Those are Phase 1+ (see `tasks.md`). Mock
providers are deterministic; raw retrieved context is never stored in traces by default (OD-008).
