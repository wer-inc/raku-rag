# 0019 — 承認後の公開経路が無い(「公開できます」は誇大)(系統 ①)

> Priority: **P3 / Medium** / Status: Open / Labels: `manufacturing`, `review`, `product-gap`, `ux`

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

- [ ] (知識化採用時)承認 → publish で承認済みドラフト内容が検索/回答に approved 根拠として反映、監査が残る。
- [ ] (非採用時)UI 文言が実体と一致し、「公開できます」が誤解を生まない。
- [ ] 埋め込み文書承認フォームが、ドラフトの実根拠と整合(自由入力 document_id の取り違えが無い)。

## スコープ外

- フル DMS / バージョン管理(002 で out-of-scope)。レビュー操作 UX 全般は [0015](0015-review-detail-ux-state-machine-mismatch.md)。

## 参照

- `src/raku_rag/manufacturing/drafts/review.py:108-133`, `src/raku_rag/manufacturing/api/drafts.py:173-193`
- `apps/web/app/components/FullSaasScreen.tsx:2072-2076,2153-2166,2265`
- 取り込み/承認ポリシー:`src/raku_rag/services/datasource_sync.py`(approval_policy), [0014](0014-approval-rules-settings-non-functional.md)
