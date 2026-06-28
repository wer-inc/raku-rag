# AGENTS.md

Instructions for Codex and other coding agents working in this repository.

## Scope

This file applies to the entire repository unless a more specific `AGENTS.md` exists in a
subdirectory.

## Project Snapshot

`raku-rag` is a local-first monorepo for a multi-tenant RAG platform with a manufacturing
solution layer and production-readiness work in progress.

Primary stack:

- Python 3.11+ core under `src/raku_rag/` plus ingestion workers in `workers/`.
- NestJS API under `apps/api/`.
- Next.js web client under `apps/web/`.
- Shared TypeScript DTOs and policy types under `packages/shared/`.
- Postgres/pgvector, S3-compatible storage, SQS/LocalStack, CDK infra under `infra/`.
- Specs, ADRs, gates, and runbooks under `specs/`, `docs/`, and `scripts/`.

Current project context is tracked in `CLAUDE.md`, especially the active production-readiness
line and the Spec Kit notes. Read that file before making non-trivial changes. Do not run
`update-agent-context.sh`; `CLAUDE.md` explicitly warns that it clobbers the curated context.

The integration branch is `develop`. Feature work normally follows numbered `NNN-<slug>`
branches and matching `specs/NNN-*` directories.

## Start-of-Task Checklist

1. Inspect the worktree with `git status --short`.
2. Read the relevant local docs/specs before editing:
   - `CLAUDE.md` for active context.
   - `docs/loop-engineering.md` for gates and loop rules.
   - `docs/production-gate-strategy.md` for production adapter gates.
   - The matching `specs/<NNN-*>/spec.md`, `plan.md`, and `tasks.md` when working on a spec.
3. Use `rg` / `rg --files` for search.
4. Treat existing uncommitted changes as user work. Do not revert or overwrite them unless the
   user explicitly asks.
5. Keep changes narrowly scoped to the request and to the owning module.

## Issue Capture Rule

When a new product, QA, production-smoke, demo, UX, security, or architecture issue is discovered
during work, add it to `issues/` in the same turn unless the user explicitly asks not to. Use the
next available `NNNN-short-slug.md` number and follow `issues/ISSUE_TEMPLATE.md`. Each issue must
capture what the issue is, where it happened, why it matters, how it should be solved, the QA
checklist, DoD, scope exclusions, and references such as run ids, correlation ids, screenshots, or
code paths. Do not include secrets, tokens, raw private data, or unrelated logs.

## Non-Negotiable Safety Rules

- Keep Tier A fast and stdlib-only. Do not add Docker, network, cloud, database, or heavy
  dependency requirements to `scripts/gate.sh a`.
- Do not weaken hard gates or tests to make implementation pass. Existing protected gate/test
  edits must be separated from `src/` implementation changes. Run `scripts/gate.sh separation`
  when touching safety/gate-related code.
- ACL is deny-by-default and must be enforced before retrieval results, answers, citations, or
  assets can leak. Preserve tenant isolation and tombstone/deletion behavior.
- For public API routes, tenant and user identity must come from signed auth context, not request
  body overrides.
- Manufacturing high-risk answers require approved and effective evidence or must return
  insufficient evidence. Draft and obsolete documents are reference-only as primary evidence.
- AI-generated manufacturing artifacts must remain `draft` until an explicit human reviewer action.
- Do not log or expose raw retrieved context, PII, secrets, tokens, refresh tokens, or internal
  auth headers. Browser code must not become the security boundary.
- No-train, audit suppression, high-risk override, production promotion, real Bedrock reindex/eval,
  and billed/cloud deploy actions require explicit human approval.

## Common Verification Commands

Prefer the smallest meaningful command for the change, then broaden when risk or shared behavior
requires it.

```bash
# Fast hard gates, default inner loop
scripts/gate.sh a

# Full Python unittest suite
scripts/gate.sh all

# Separation invariant for protected gates/tests
scripts/gate.sh separation

# Postgres/pgvector/RLS tier, requires Docker Compose
scripts/gate.sh b
```

Python:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t . -p 'test_*.py' -q
PYTHONPATH=src python3 -m unittest tests.unit.test_python_sdk_client -v
python3 -m py_compile path/to/file.py
```

Node/TypeScript:

```bash
npm run build:shared
npm run typecheck
npm run test:api
npm run build --workspace @raku-rag/web
npm run typecheck --workspace @raku-rag/api
```

Local stack:

```bash
cp .env.example .env
docker compose up -d
scripts/docker-compose-smoke.sh
npm run dev:api
npm run dev:web
```

CDK/infra checks:

```bash
cd infra/cdk
npm ci
npm run build
npx cdk synth
```

Only run deploy, production smoke, Bedrock live eval, or billed reindex commands after explicit
human approval.

## Coding Conventions

Python:

- Preserve the stdlib-first core where existing code does so.
- Use the existing service/provider/interfaces boundaries in `src/raku_rag/`.
- Python formatting targets line length 100 (`black`/`ruff` settings in `pyproject.toml`).
- Keep production adapters behind factories/settings so the deterministic default remains intact.

TypeScript/NestJS:

- Keep the NestJS API a thin facade where the Python answer-service or shared domain logic owns
  RAG truth.
- Update `packages/shared` DTOs and OpenAPI contracts when API request/response shapes change.
- Run API e2e tests for controller/auth/OpenAPI changes.

Next.js:

- Use `@raku-rag/shared` DTOs and `NEXT_PUBLIC_API_BASE`.
- The Vercel AI SDK may help client ergonomics, but authorization, tenant isolation, ProviderPolicy,
  groundedness, citations, and logging policy enforcement belong on the server side.
- Respect residency and telemetry constraints described in `apps/web/README.md`.

Database/infra:

- Postgres migrations live under `infra/db/migrations/postgres/` and should have matching down
  migrations unless there is a documented reason.
- Preserve RLS, tenant context, and idempotent migration behavior.
- CDK changes should synth cleanly; live deploys are human-gated.

## Architecture Notes

- Reuse the 001 base platform features instead of redefining them: tenancy, ACL pre-filter,
  signed-token auth, citation/groundedness, ingestion/search/answer/deletion, evaluation/cost, and
  observability.
- The manufacturing layer is an overlay. Its hard rules include high-risk evidence gating,
  draft-only AI outputs, obsolete/draft evidence handling, no-train policy, and audit coverage.
- `ProductionSystem` in `src/raku_rag/production.py` is the Postgres-backed analog of the in-memory
  MVP system. Parity with existing hard gates matters more than duplicating business logic.
- Runtime profile defaults must remain deterministic unless a task explicitly changes production
  wiring behind configuration.

## Files and Areas to Handle Carefully

- `goal.md`, `memo.txt`, generated context files, and local deployment outputs may be user scratch
  or environment state. Inspect before touching.
- `LP/assets/`, `node_modules/`, build outputs, generated bundles, and binary assets are usually not
  relevant to code changes.
- `scripts/gate.sh`, `tests/security/**`, `tests/manufacturing/unit/**`, hard-gate tests, and
  Postgres migrations are protected safety surfaces. Edit deliberately and verify separation.
- Secrets belong in environment variables or secret stores, never in committed files.

## Code Review (レビュー方針)

RAG SaaS のコードレビューは3モードで実施する。共通原則・正解情報の所在(実パス)・レイヤ↔実
ディレクトリ対応・運用フローの **SSOT は `docs/code-review/policy.md`**。各モードの手順は対応する
`SKILL.md` を**手順書として直接読んで**実行する(Claude Code 以外のエージェントはスキル起動不可のため)。

- モード1 マッピング(フェーズ0、最初に1回。構造把握のみ・バグ指摘禁止)— `.claude/skills/review-map/SKILL.md`
- モード2 境界監査(FE↔BE↔infra の契約点を境界 / モジュール単位で繰り返し)— `.claude/skills/boundary-audit/SKILL.md`
- モード3 テナント分離 / RAG 品質の網羅監査(「1箇所漏れたら全部漏れる」前提)— `.claude/skills/tenant-audit/SKILL.md`

フロー: モード1 → モード2(境界ごと反復)→ モード3。全指摘に `file:line` 根拠、各回末尾で
カバレッジ自己チェック必須。

