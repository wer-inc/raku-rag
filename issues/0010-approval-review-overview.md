# 0010 — 承認 / 文書承認 / レビューキュー 課題クラスタ(概要)

> Status: **Open** / Author: コードレビュー(Claude Code 経由, 2026-06-28)
> 対象: 製造業 RAG(002 ソリューション層 + 015 アンサーワークスペース)の「承認まわり」3系統の
> 設計・実装・UI/UX を file:line で突き合わせた結果。各課題の詳細・対応は個別 issue(0011–0016)。

## 一行サマリ

**「承認」は実は 3 つの独立した系統**で、中核の**安全ゲートは堅牢**だが、その周辺の
**権限(RBAC)・永続化・設定 UI・状態機械整合**に、実テナント運用で表面化する穴がある。

## 「承認」の 3 系統(用語整理)

| 系統 | 状態機械 | 実装(SSOT) | 画面 |
|---|---|---|---|
| **① AI ドラフトのレビュー** | `draft → in_review → approved \| rejected \| archived` | `src/raku_rag/manufacturing/drafts/review.py`, `api/drafts.py` | レビューキュー `/reviews`、レビュー詳細 `/reviews/:id`(`FullSaasScreen.tsx` `ReviewQueueBody`/`ReviewDetailBody`) |
| **② 文書承認** | `draft → pending_review → approved → obsolete`(前進のみ) | `src/raku_rag/manufacturing/ingestion/approval.py` | 文書承認キュー `/reviews/documents`(`DocumentApprovalQueueBody`) |
| **③ 承認ルール(設定)** | —(現状ルール表示のみ) | `manufacturing/api/policy.py` `governance_status` | 承認ルール `/reviews/settings`(`ApprovalWorkflowBody`) |

加えて **安全ゲート**(`manufacturing/safety/gate.py`)が、回答段で「高リスクは承認済み＋発効中の引用が
無ければ断定不可」「draft/obsolete は一次根拠にしない」「obsolete は警告」を強制する。

## まず良い点(変更不要・回帰させないこと)

- **安全ゲートの判定ロジック自体は設計どおり堅牢。** 高リスク判定 ∧ approved+effective 引用なし ⇒
  `blocked` + `APPROVED_CITATION_MISSING`(`safety/gate.py:173-180`)。`is_effective` は未来日付/欠落/
  不正をすべて invalid に倒す fail-safe(`gate.py:49-61`)。
  **ただし「approved+effective」と判定する“証拠の妥当性”側に穴がある**(失効未実装・obsolete 復活・
  自己申告・stale キャッシュ)。これは [0017](0017-safety-gate-evidence-validity.md) で扱う。
- **AI ドラフトの承認は人手必須が不変条件として担保。** `decide()` は reviewer 不在の approve を
  `PermissionError` で弾き、artifact を draft のまま据え置く(`drafts/review.py:108-114`)。
  `created_by=ai` は承認で書き換えない(provenance 保持)。
- **状態遷移は監査される。** ドラフトの generate/assign/review、文書の transition/import/supersede が
  すべて参照 ID のみで `AuditLogWriter` に記録(`api/drafts.py:209-257`, `ingestion/approval.py:241-266`)。
- **文書承認ワークフローは前進専用**で obsolete の復活を禁止(`ingestion/approval.py:190-201`)。

## Issue 一覧(優先度順 = 着手順)

| # | 系統 | Issue | 優先度 |
|---|------|-------|--------|
| [0011](0011-rbac-reviewer-cannot-approve.md) | ①② | `reviewer`/`ops_owner` ロールが承認できない RBAC 矛盾 | **P0 / High** |
| [0017](0017-safety-gate-evidence-validity.md) | gate | 安全ゲートが誤った承認状態の証拠を使い得る(失効/復活/自己申告/stale) | **P1 / High** |
| [0012](0012-draft-review-queue-not-persisted.md) | ① | レビューキューがプロセス内メモリで**非永続**(専用テーブルが存在するのに未使用) | **P1 / High** |
| [0014](0014-approval-rules-settings-non-functional.md) | ③ | 「承認ルール」画面が編集不能＋GET/PUT エンドポイント未実装 | P2 / Medium |
| [0015](0015-review-detail-ux-state-machine-mismatch.md) | ①② | レビュー詳細の操作が状態機械とズレ／重複・確認/二重送信なし | P2 / Medium |
| [0013](0013-review-badge-and-list-staleness.md) | ① | レビューバッジ/一覧の陳腐化・トリアージ/ページング無し | P2 / Medium |
| [0019](0019-no-publish-path-after-approval.md) | ① | 承認後の公開経路が無い(「公開できます」は誇大) — **Resolved 2026-07-03**(publish エンドポイント+UI+監査で知識化) | P3 / Medium |
| [0018](0018-approval-audit-trail-gaps.md) | ①② | 承認の監査証跡ギャップ(理由未記録/actor 誤記/citations 未配線) | P3 / Medium |
| [0016](0016-document-approval-skip-and-workflow-authz.md) | ② | 文書承認 skip-ahead + 内部境界でロール未検証 + reject/archive の actor 欠落 | P3 / Low–Medium |

## 完了定義(このクラスタ)

1. 純粋な `reviewer`(tenant_admin なし)で、ドラフトの割当・承認・却下、文書の承認・旧版化が**通る**。
2. 承認済み/レビュー中ドラフトが answer-service 再起動・複数インスタンス間で**保持・共有**される。
3. レビューキュー nav バッジが**実際の未レビュー件数**を反映する。
4. 「承認ルール」画面が、少なくとも誤解を招く非機能 UI でない(編集可能 or 明示的に読み取り専用)。
5. UI が提示する遷移は、すべてバックエンド状態機械で**合法**なものだけ。
6. 高リスク回答の根拠が「approved かつ発効中かつ失効していない」を**サーバ側だけ**で判定し、
   obsolete 文書が import で復活したり、呼び出し側の自己申告で「承認済み」扱いになったりしない。
7. 承認/却下の**理由と実行者**が監査ログに正しく残る。

## 参照

- メモリ: `live-fullstack-workspace`, `datasource-trust-policy-review`, `live-smoke-catches-realpg-mfg-gaps`
- 設計: `specs/002-manufacturing-field-knowledge-rag/{spec.md,data-model.md,contracts/}`, `specs/full-saas/gaps.md`
- 既存クラスタ: [README](README.md)(基盤安定化 0000–0005)
