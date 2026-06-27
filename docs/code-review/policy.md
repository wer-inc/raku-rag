# RAG SaaS コードレビュー方針(SSOT)

このリポジトリ(`raku-rag` — マルチテナント RAG SaaS モノレポ)のコードレビュー共通方針。
レビューは3つのスキル(モード)で実施し、全モードが共有する **共通原則** と **正解情報の所在** を
この1ファイルに集約する(SSOT)。各モードの具体手順は対応するスキル定義を参照。

| モード | 役割 | スキル(`/`) | 定義ファイル |
|---|---|---|---|
| 1 マッピング | フェーズ0。構造把握(最初に1回) | `/review-map` | `.claude/skills/review-map/SKILL.md` |
| 2 境界監査 | 層と層の契約点を突き合わせ(繰り返し) | `/boundary-audit` | `.claude/skills/boundary-audit/SKILL.md` |
| 3 テーマ別ディープダイブ | テナント分離 / RAG を網羅的に潰す | `/tenant-audit` | `.claude/skills/tenant-audit/SKILL.md` |

> Codex 等、Claude Code スキルを起動できないエージェントは、上記 `SKILL.md` を**手順書として直接読んで**実行する。

---

## 共通原則(全モードで厳守)

- **境界とテーマで縦に刺す。** 各層の内部を網羅するより、層をまたぐ seam(型・enum・env・権限・テナント境界)を優先する。バグの大半はそこで起きる。
- **正解との突き合わせ。** 実装単体を眺めて感想を言わない。仕様・スキーマ・ポリシーと突き合わせて「あるべき姿との差分」を指摘する。正解情報が無ければ「正解未発見」と明記する。
- **根拠必須。** すべての指摘に `file:line` を添える。辿っていない箇所について断定しない。
- **推測は隔離。** 仕様に「書かれていること」と自分の「推測」を必ず区別し、推測には `[推測]` を付ける。
- **スコープ厳守。** 指定されたスコープ外には踏み込まない(関連時のみ参照)。
- **カバレッジ自己チェック。** レビュー終了時、フェーズ0(モード1)の地図と突き合わせて「見た／見ていない」を必ず申告する。

---

## レイヤ ↔ 実ディレクトリ対応(「FE / BE / infra」の読み替え表)

レビュー観点の汎用語(frontend / backend / infra)は、本リポジトリでは以下に対応する。

| 汎用語 | 実体 |
|---|---|
| **FE** | `apps/web`(Next.js, `app/` ルーティング, `middleware.ts`) |
| **BE** | `apps/api`(NestJS API ファサード)/ `apps/answer-service`(Python answer-service)/ `src/raku_rag`(RAG コア)/ `workers`(ingestion) |
| **共有契約** | `packages/shared/src/dto/*` と `packages/shared/src/policy/*`(TS DTO / ポリシー型 = **FE↔BE 契約の SSOT**) |
| **infra** | `infra/cdk`(CDK)/ `infra/db/migrations/postgres`(スキーマ・RLS)/ `infra/db/init`/ `infra/otel`/ `infra/localstack` |

データフローの基本経路:
`web(apps/web) → NestJS API(apps/api) → Python answer-service(apps/answer-service / src/raku_rag) → Postgres/pgvector・ベクトル検索・外部 LLM`

---

## 正解情報の所在(実パス)

突き合わせの「正解」はここから探す。見つからないものは「未発見」と明記する。

| 種類 | パス |
|---|---|
| 仕様 / 設計 | `specs/NNN-*/spec.md`, `plan.md`, `data-model.md`, `quickstart.md` |
| OpenAPI(設計) | `specs/001-rag-platform/contracts/openapi.md`, `specs/002-manufacturing-field-knowledge-rag/contracts/mfg-openapi.md` ほか |
| OpenAPI(実装) | `apps/api/src/openapi/openapi.controller.ts`(export: `apps/api/scripts/export-openapi.cjs`) |
| DB スキーマ / RLS | `infra/db/migrations/postgres/*.sql`(RLS の起点: `0001_core_rls.sql`, `0002_policy_profile_visual_rls.sql`)/ ランナー: `src/raku_rag/migrations` |
| DB 拡張(pgvector 等) | `infra/db/init/01-extensions.sql` |
| 共有 DTO / ポリシー型 | `packages/shared/src/dto/*`, `packages/shared/src/policy/*` |
| テナント分離コア | `src/raku_rag/core/tenancy.py`, `core/security/acl.py`, `core/security/token.py` |
| ベクトル検索フィルタ | `src/raku_rag/providers/vectorstores.py` |
| 監査ログ | `src/raku_rag/observability/audit.py` |
| env | `.env.example`(ルート) |
| 規約 / lint / ゲート | `pyproject.toml`(ruff/black/mypy), `.pre-commit-config.yaml`, `scripts/gate.sh`, `.specify/memory/constitution.md` |
| ADR / ハードニング | `adr.md`, `architecture-hardening.md`, `security-governance-plan.md` |

---

## 運用フロー

1. **モード1(`/review-map`)** を最初に1回。地図と「レビュー作業計画」を得る。
2. 計画に沿って **モード2(`/boundary-audit`)** を境界 / モジュール単位で繰り返す。
3. **モード3(`/tenant-audit`)** をテナント分離・RAG で(規模次第で経路を分割して複数回)走らせる。

各回の `file:line` 根拠と末尾のカバレッジ自己チェックが、巨大コードベースで「見た／見ていない」を管理する生命線。
