# 0019 — 承認後の公開経路が無い(「公開できます」は誇大)(系統 ①)

> Priority: **P3 / Medium** / Status: **Resolved (2026-07-03)** / Labels: `manufacturing`, `review`, `product-gap`, `ux`

## 解決サマリ(2026-07-03)

**意図 = 知識化する(推奨案)を採用し、承認後の publish ステップを実装した。**

- **サービス層** `DraftService.publish`(`src/raku_rag/manufacturing/api/drafts.py`)+
  `ManufacturingSystem.publish_draft`(`manufacturing/app.py`): `status=approved` のドラフトのみ、
  決定論レンダラ(`manufacturing/drafts/render.py`、未確定項目は 【未確定・要確認】 マーカー保持)で
  markdown 化し、**再利用した** `ingest_manufacturing`(001 parse→chunk→embed→index + メタデータ付与)で
  ドラフトの collection(未指定時 manuals)へ `pub_<artifact_id>` として ingest。メタデータは
  `approval_status=approved` + `effective_date=today` + `approved_by=承認レビューア` +
  `extra.approval_source_detail="draft_publish"` + 生成元 provenance(`published_from_draft_id` /
  `source_document_ids` / `source_citations`)。公開は承認とは**別の、帰属可能な人間の操作**
  (principal 由来 actor 必須、無帰属/AI は `PermissionError`)。ハッシュチェーン監査に
  `draft.published`(actor / draft / 新 document_id)を記録し、ドラフトへ
  `published_document_id` / `published_by` / `published_at` をスタンプ(Postgres store は payload
  jsonb 搬送 — スキーママイグレーション不要)。二重 publish はサーバ側 409。
- **エンドポイント**: answer-service `POST /internal/manufacturing/drafts/{id}/publish`
  (identity は署名済み principal ヘッダのみ)+ API façade `POST /v1/manufacturing/drafts/{id}/publish`
  (`assertReviewApprovalAllowed` — review/approve と同じ reviewer/admin ゲート)。
- **UI**(`ReviewDetailBody`): 誇大だった「正式に公開できます」静的文言を、承認済み・未公開時の
  「ナレッジとして公開」ボタン(ConfirmDialog: 公開すると回答の根拠として利用可能になります)に置換。
  公開後は published_at + 公開文書リンク付きの「公開済み」表示。承認ボタン文言「承認・公開」→「承認」。
- **テスト**: `tests/manufacturing/test_draft_publish.py`(approved のみ publish 可 / 無帰属 actor 拒否 /
  冪等 409 / 監査記録+チェーン健全 / **公開 FAQ が answer 経路で approved 引用として回答に使われる** /
  承認だけでは知識化されない対照)+ `tests/postgres/test_draft_store_realpg.py` に publish フィールドの
  payload round-trip + `apps/api/test/manufacturing.e2e-spec.ts` に publish のロールゲート(reviewer 200 /
  field_user 403)。

**残り(スコープ外のまま)**: 埋め込み「根拠文書レビュー」フォームの source_document_ids バインドは
[0015](0015-review-detail-ux-state-machine-mismatch.md) の未対応スライスとして継続。

## 背景(なぜ今)

AI ドラフトのレビュー画面は「AI 出力は人手レビューで**承認されるまで正式な知識にはならない**」
(`FullSaasScreen.tsx:2265`)と謳い、承認後は「**承認済み — このドラフトは正式に公開できます**」
(`:2072-2076`)と表示する。だが実装上、承認は**ステータスを `approved` にするだけ**で、承認済みドラフトの
内容を検索可能な正式 Document として登録する経路が**存在しない**。UI の約束と実体が乖離している。

## 現状(根拠)

- `ReviewWorkflow.decide(decision='approved')`(`drafts/review.py:108-133`)は `status`/`reviewer_*`/
  `approval_decision` 等の**フィールドを書くだけ**。
- `DraftService.review`(`api/drafts.py:173-193`)はそのコピーを返すのみで、下流の ingest/承認/公開を**呼ばない**。
- 承認済みドラフトの `content.items`(チェックリスト/FAQ 等)を「approved な検索対象 Document」に変える
  エンドポイント/呼び出しが無い。
- 同画面の埋め込み「文書承認」フォーム(`:2153-2166`)は**無関係な自由入力 `document_id`** を操作するだけで、
  いま承認したドラフトの `source_document_ids` とは紐づかない(→[0015](0015-review-detail-ux-state-machine-mismatch.md))。
- つまり「承認済み = 公開済み/知識化済み」という UI の含意が成立しない。

## 影響

- レビューアは「承認したのに、その内容が回答根拠として検索に出てこない」状態に直面し得る。
- 「正式な知識になる」というプロダクト価値(レビュー → ナレッジ反映)のループが閉じていない。

## 提案作業(何をどう対応)

まず**プロダクト意図を確定**:承認済みドラフト(FAQ/チェックリスト/トラブル報告 等)は
「検索可能な approved Document として知識化する」のか、「人が参照する成果物として置くだけ」なのか。

- **意図 = 知識化する(推奨, FAQ/checklist は特に):**
  1. **publish ステップを実装**:承認 → 承認済みドラフト `content` を Document として ingest し、
     承認ポリシー由来の `approval_status`(既定は trusted→approved / それ以外 pending_review、
     [0014](0014-approval-rules-settings-non-functional.md)/`datasource_sync` の方針に整合)で登録。
     新規 `POST /v1/manufacturing/drafts/:id/publish`(または review approve の後続処理)として実装し、
     監査(`draft.publish`)を残す。生成元 citations を継承。
  2. **UI**:承認後に publish 結果(生成された document_id・承認状態)を表示。埋め込み「文書承認」フォームは
     ドラフト自身の `source_document_ids` にバインド(自由入力をやめる)。
- **意図 = 知識化しない:**
  - 「公開できます」の文言を実体に合わせて修正(例「承認済み — 成果物として確定しました(検索反映は別途)」)。
  - 埋め込み文書承認フォームは削除し `/reviews/documents` へ誘導。

## 受け入れ条件(DoD)

- [x] (知識化採用時)承認 → publish で承認済みドラフト内容が検索/回答に approved 根拠として反映、監査が残る。
      → `tests/manufacturing/test_draft_publish.py::TestPublishedKnowledgeIsCitable`
- [x] (非採用時)UI 文言が実体と一致し、「公開できます」が誤解を生まない。
      → 知識化を採用。UI は「未公開(公開ボタン)」/「公開済み(文書リンク)」を実体どおり表示。
- [ ] 埋め込み文書承認フォームが、ドラフトの実根拠と整合(自由入力 document_id の取り違えが無い)。
      → [0015](0015-review-detail-ux-state-machine-mismatch.md) の未対応スライスとして継続(本 issue のスコープ外)。

## スコープ外

- フル DMS / バージョン管理(002 で out-of-scope)。レビュー操作 UX 全般は [0015](0015-review-detail-ux-state-machine-mismatch.md)。

## 参照

- `src/raku_rag/manufacturing/drafts/review.py:108-133`, `src/raku_rag/manufacturing/api/drafts.py:173-193`
- `apps/web/app/components/FullSaasScreen.tsx:2072-2076,2153-2166,2265`
- 取り込み/承認ポリシー:`src/raku_rag/services/datasource_sync.py`(approval_policy), [0014](0014-approval-rules-settings-non-functional.md)
