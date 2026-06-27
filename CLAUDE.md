<!-- SPECKIT START -->
> Current active line of work (2026-06-25): **020-prod-readiness** — the live-verified `/goal` prod
> loop (ledger SSOT at `specs/prod-readiness/ledger.json`), built on the implemented 002 solution
> layer below. The full stack is also deployed on AWS (LIVE & billing); see "Beyond the 002/015
> baseline" below the SPECKIT block. (This managed block is hand-curated — do NOT run
> `update-agent-context.sh`, which clobbers it with a 3-line plan-path stub.)

## Active Feature: 002-manufacturing-field-knowledge-rag (Solution Layer — implemented; T001–T072 checked + 20-item design-gap backlog open; committed, gate green)

Manufacturing Field Knowledge RAG built **on top of** the 001 base platform (do NOT redefine base
features — reference them). Plan & design artifacts complete (GQ1=block, GQ2=customer 1yr/audit 1yr
resolved). `tasks.md` is fully checked (T001–T072 + sub-tasks, all `[x]` = 実装済み). The cross-spec
implementation (002 manufacturing + 003/006/010 + observability/providers/workers/SDK/infra/tests) is
committed on `002-manufacturing-field-knowledge-rag` (now folded into the `develop` trunk — see
"Repository / branches" below); the GitHub `gate` workflow is green as of `1e2abb5`. A 2026-06-20 design-vs-impl audit filed **20 confirmed gap-remediation items** (2 safety-boundary,
reproduced) into the specs' `tasks.md` (§Gap Remediation Backlog) — implementation deferred; these are why
"all tasks `[x]` + gate green" is necessary but NOT sufficient for "design complete". Local
`scripts/gate.sh all` GREEN is also necessary but not sufficient — confirm the GitHub `gate` run
(Tier A is stdlib-only; Tier B Postgres/RLS and RT1 compose smoke run only on GitHub runners).

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

## Repository / branches

Default & integration branch: **`develop`** (set 2026-06-23) — open PRs against `develop`. There is
no `main`/`master`. Spec Kit workflow: feature work lives on numbered `NNN-<slug>` branches (matching
`specs/NNN-*`) that merge into `develop`. `develop` was seeded as
`002-manufacturing-field-knowledge-rag ⊕ 015-mfg-answer-workspace-poc` and now carries the full
implemented stack: RAG core + manufacturing safety overlay + the answer-workspace **frontend**
(`apps/web`, goal.md flows) on the live `web → NestJS API → Python answer-service → Postgres` path.
(Earlier numbered branches 003–014 are already merged into the 002 line that `develop` descends from.)
Current active line of work: **020-prod-readiness** (the live-verified `/goal` prod loop; ledger SSOT
at `specs/prod-readiness/ledger.json`).

## Beyond the 002/015 baseline (already landed on `develop`)

The SPECKIT block above describes the 002 solution layer; the following also ships on `develop` and
is NOT reflected there:
- **AWS production deploy (LIVE & billing as of 2026-06-25).** CDK stack under `infra/cdk/`
  (`minimalSpec` low-cost profile: Aurora 1-instance, small Fargate, Langfuse off; `aws-nextjs`
  same-origin web+API behind one ALB, optional ACM TLS). Deploy is via **GitHub Actions OIDC** (no
  local Docker) — see `infra/cdk/DEPLOY.md` / `DEPLOY-CI.md`. Post-deploy migrate+seed runs in-VPC as
  an ECS RunTask.
- **Embedding providers**: OpenAI `text-embedding-3-small @256` is wired as an **opt-in** alternative
  to the default offline hashing embedder (#31).
- **Datasource connectors** (end-to-end frontend↔API↔answer-service): MySQL / Confluence / Notion /
  Box / S3 / URL / kintone, via `src/raku_rag/services/datasource_sync.py`. SSRF hardening
  (IP-pinning, allowlists, auth-strip) and a config-driven trust/approval policy gate apply.
- **Japanese-aware retrieval**: CJK-bigram tokenizer (recall@k 0.80 → 1.0).
- **Live quality & safety scorecard** surfaced on the 品質・KPI screen, with the eval harness wired to
  the running stack (`scripts/demo/quality_scorecard.sh`).
- **Sellable PoC demo package**: `scripts/demo/` (curated JP KB, `demo_up.sh` one-command boot,
  `DEMO.md` runbook).

## Code Review (レビュー方針)

RAG SaaS のコードレビューは3モードのスキルで実施する。共通原則・正解情報の所在(実パス)・
レイヤ↔実ディレクトリ対応・運用フローの **SSOT は `docs/code-review/policy.md`**。

- **`/review-map`** — モード1 マッピング(フェーズ0、最初に1回。構造把握のみ、バグ指摘禁止)
- **`/boundary-audit`** — モード2 境界監査(FE↔BE↔infra の契約点を境界 / モジュール単位で繰り返し)
- **`/tenant-audit`** — モード3 テナント分離 / RAG 品質の網羅監査(「1箇所漏れたら全部漏れる」前提)

フロー: モード1 → モード2(境界ごと反復)→ モード3。全指摘に `file:line` 根拠、各回末尾で
「見た／見ていない」カバレッジ自己チェック必須。スキル定義は `.claude/skills/{review-map,boundary-audit,tenant-audit}/SKILL.md`。
