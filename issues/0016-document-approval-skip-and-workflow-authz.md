# 0016 — 文書承認の skip-ahead + 内部境界でロール未検証 + reject/archive の actor 欠落(系統 ②)

> Priority: **P3 / Low–Medium** / Status: Open / Labels: `manufacturing`, `approval`, `authz`, `defense-in-depth`

## 背景(なぜ今)

文書承認(`ApprovalWorkflow`)と AI ドラフトの承認(`ReviewWorkflow`)は、ドメイン層では**実行者のロールを
記録するだけで強制しない**設計で、認可は NestJS facade(`assertAdminMutationAllowed`)頼り。answer-service の
内部ルートは共有シークレットのみで、ロール再検査が無い(防御多層の欠如)。また文書側は `pending_review` を
飛ばして一発承認でき、reject/archive は実行者不在を許容する。

## 現状(根拠)

- **skip-ahead**:`ingestion/approval.py:52-57` の rank で「前進なら飛ばし可」。`draft(0)→approved(2)` が
  一発で通る(`:96-101` のコメントが明言、`_assert_legal_transition` `:190-201` は後退のみ禁止)。
  → 一度も `pending_review` を経ない(=人手レビュー段を踏まない)承認が可能。
- **WF 層でロール未強制**:`ApprovalWorkflow.transition`(`:85-116`)は `actor.user_id`/`actor.roles` を
  audit に記録(`:113-114,257`)するが、**承認者ロールの検査をしない**。`ReviewWorkflow.decide` も
  「AI は自己承認不可」(`drafts/review.py:108-114`)のみで、承認者 = 割当 reviewer_id / reviewer_group 所属 か、
  承認者 ≠ 作成者 のチェックは無い(職務分掌・maker-checker 無し)。
- **内部境界の認可欠如**:answer-service `do_POST` は `X-Internal-Auth` 共有シークレットのみで通し
  (`apps/answer-service/server.py` 内 internal ルート)、x-raku-* ヘッダの身元をそのまま信頼。承認/割当/レビューの
  **ロール再検査が無い**(唯一のロールゲートが NestJS facade だけ)。Dagster 等 HTTP 以外の呼び出し元では
  facade を経由しない。
- **reject/archive の actor 欠落**:`drafts/review.py:34-35,123-128,137-142` — `approved` のみ実行者必須。
  `rejected`/`archived` は `reviewer=None` を許容し `artifact.reviewer_id`(None もあり得る)へフォールバック。
  `archived` は draft から直接到達可能 → 未割当ドラフトを実行者不明で終端化できる。

## 影響

- 「軽量承認」設計の範囲内(skip-ahead は GAP-F06 で意図的)だが、安全カテゴリ文書まで一発承認できると
  レビュー段の意味が薄れる。
- facade を迂回する経路(内部直叩き / 非 HTTP 呼び出し)でロール強制が抜ける。
- reject/archive の実行者が監査に残らないケースがある。

## 提案作業(何をどう対応)

1. **承認者ロールをドメイン層でも検査(防御多層)**:`ApprovalWorkflow.transition` / `ReviewWorkflow.decide` に
   actor の roles を渡し、承認/旧版化/レビューには reviewer 級ロール(→[0011](0011-rbac-reviewer-cannot-approve.md) の
   `REVIEW_APPROVAL_ROLES` と同義)を要求。facade と二重で守る。
2. **内部境界の再検査**:answer-service の承認/割当/レビュー internal ルートで、x-raku-roles を見て
   承認者級ロールを再確認(共有シークレット + ロールの二段)。
3. **安全カテゴリは pending_review 必須(任意・設計判断)**:safety/quality/equipment 区分の文書は
   `draft→approved` 直行を禁止し `pending_review` を経由必須に(`_assert_legal_transition` に区分条件を追加)。
   そうしない場合は data-model に「skip-ahead は意図的」と明記して曖昧さを消す。
4. **職務分掌(maker-checker, 任意)**:承認者 = 割当 reviewer_id か reviewer_group 所属、かつ承認者 ≠ 作成者を強制。
5. **reject/archive にも実行者必須**:`approved` と対称に、`rejected`/`archived` も attributable な actor を要求
   (または system actor を明示記録)。

## 受け入れ条件(DoD)

- [ ] facade を迂回しても承認者級ロール無しでは承認/旧版化/レビューできない。
- [ ] (採用時)安全カテゴリ文書は pending_review 未経由で approved にできない、または skip 意図が spec に明記。
- [ ] reject/archive の実行者が必ず監査に残る。
- [ ] (採用時)自己承認(承認者=作成者)が拒否される。

## スコープ外

- フル e-signature / 多段ワークフロー(002 で out-of-scope)。RBAC の facade 側修正は [0011](0011-rbac-reviewer-cannot-approve.md)。

## 参照

- `src/raku_rag/manufacturing/ingestion/approval.py:52-57,85-116,190-201`, `src/raku_rag/manufacturing/drafts/review.py:34-35,108-128,137-142`
- `apps/answer-service/server.py`(internal approval/assign/review ルート, X-Internal-Auth), `apps/api/src/manufacturing/manufacturing.controller.ts:186-275`
