# 基盤安定化スコープ — CTO 調査結果(2026-06-28)

> Status: **Accepted / 0001・0003 は repo-side 着手済み(2026-06-28)** / Author: CTO レビュー(Claude Code 経由)
> 対象: 多数企業が導入するマルチテナント RAG SaaS を「最速で安定化」「柔軟なデータ基盤に」する、という問いへの回答。

## 一行回答

**4層スタック(メダリオン / dbt・Cube / Graph DB / MCP)を作る方向には行かない。** 柔軟性を生む
"継ぎ目(seam)" は既に揃っているので、新しい抽象は足さず、**「多数テナントが乗ると壊れたら不可逆」な
耐力壁(4つ)だけを "規律で守る / 緑のゲートで通る" 段階から "構造的に破れない / 実バックエンドで実証済み"
段階へ引き上げる**。それ以外は全部スコープ凍結。これが最速の安定化。

## 「柔軟性はもう足りている」— なぜそう言えるか

柔軟なデータ基盤の核心部品はすでに実装済み(詳細・根拠は [0000](0000-context-data-governance-adoption.md)):

- **埋め込みモデルをテナント単位で無停止差し替え** — `src/raku_rag/services/reindex.py` の `ReindexPlan`
  (`tenant_id` / `target_embedding_model_version`、並行ビルド→明示スイッチ→旧チャンク tombstone)
- **インターフェース継ぎ目** — `src/raku_rag/interfaces/base.py`、プロバイダ抽象、`PostgresVectorStore`
- **定量/定性ルーター** — `src/raku_rag/services/structured_query.py`(`services/answer.py:127` で配線済み)
- **コネクタ枠 + 信頼/承認ポリシー、業種プロファイル + `KPIDefinition`**

> 柔軟性 = 安定した契約 + 差し替え可能なバックエンド + 無停止再インデックス。**3つとも既にある。**
> いま抽象を足すと "硬くすべき表面積" が増え、安定化が遅れる。**柔軟であるための正しい行動は、
> 継ぎ目を凍結して固めること。**

## Issue 一覧(優先度順 = 着手順)

| # | 耐力壁 | Issue | 優先度 |
|---|--------|-------|--------|
| [0001](0001-live-backend-multitenant-release-gate.md) | C | 実 PG / 多テナント soak を**リリースゲート**へ昇格 | **P0** |
| [0002](0002-tenant-isolation-structural-invariant.md) | A | テナント分離を「規律」から「**構造的不変条件**」へ | P1 |
| [0003](0003-migration-discipline.md) | B | スキーマ/**マイグレーション規律**(順序・冪等・全テナント適用証明) | P1 |
| [0004](0004-freeze-version-contracts.md) | D | **契約 v1 凍結** + バージョニング | P2 |
| [0005](0005-non-goals-stop-line.md) | — | **Non-Goals / Stop-Line**(いまやらないこと) | — |

## 「安定した基盤」の完了定義(これを満たしたら設計パートナー企業のオンボード開始)

実 PG・N テナント並行で:

1. クロステナント漏れ 0(注入された未スコープ経路は CI で落ちる)
2. 削除済みコンテンツが再出現しない(tombstone)
3. 埋め込みモデル差し替えが無停止で完走(reindex 並行スイッチ)
4. 全マイグレーションが全テナントに適用済みと証明できる
5. 契約 v1 が固定

**ここまで。4層スタックは完了定義に入れない。**

## 内面化すべき唯一の戦略リスク

**「ゲート緑 / 全タスク `[x]` = 完了」という誤認。** インメモリ緑ゲートは「多テナント・実バックエンドで
初めて出るバグ」を隠す(根拠: メモリ `live-smoke-catches-realpg-mfg-gaps` / `ci-gate-is-the-authority`)。
多数の企業を乗せ始める瞬間にこの誤った自信が最も高くつく。**だから [0001](0001-live-backend-multitenant-release-gate.md) を最初に置く。**

## 進め方

現行の **020-prod-readiness ループ(ledger SSOT: `specs/prod-readiness/ledger.json`)を 0001–0004 に
照準し直し、stop-line([0005](0005-non-goals-stop-line.md))を ledger に明記**するのが最短。

## 2026-06-28 repo-side 対応

- 0001: `gate.yml` の Tier B を常時実行に変更し、`tests/postgres/test_multitenant_release_soak.py`
  で実 PG / 3テナント / ingest→search→answer→delete→reindex の漏洩 0 を検証対象に追加。
- 0003: `tests/contract/test_migration_discipline.py`、`scripts/postgres-migration-smoke.sh`、GitHub
  Tier B の全 numbered migration up/down smoke により、連番欠落・down pair 欠落・smoke 適用漏れを検出。
- 0005: visual/PDF は production ingestion の対象に入ったため、stop-line を「新規 VLM 基盤の過剰実装を
  しない」へ調整。
