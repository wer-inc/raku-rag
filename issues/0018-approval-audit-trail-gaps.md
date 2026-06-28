# 0018 — 承認の監査証跡ギャップ(理由未記録 / actor 誤記 / citations 未配線)(系統 ①②)

> Priority: **P3 / Medium** / Status: Open / Labels: `audit`, `manufacturing`, `compliance`, `HR5`, `FR-MFG-021`

## 背景(なぜ今)

Hard Rule 5 / FR-MFG-010b / FR-MFG-021 は「**レビューア + 決定理由 + 使用根拠 + 全状態遷移**」の監査を要求。
状態遷移自体は監査されている(良い点)が、(1) 決定理由、(2) 実行者の正しい記録、(3) 生成根拠 citations に
取りこぼしがある。監査が「誰が・なぜ承認/却下したか」を完全には残せていない。

## 現状(根拠 / 3 サブ課題)

### A. レビューの「決定理由(コメント)」が監査に残らない
- `DraftService._audit_transition`(`api/drafts.py:235-256`)は `reason=artifact.type.value`(=ドラフト**種別**、
  例 "faq")を記録。レビューアの自由記述コメントは**監査エントリに入らない**。
- コメントは in-memory の `DraftArtifact.review_comment` にしか乗らず(`drafts/review.py:133`)、
  ストアが揮発(→[0012](0012-draft-review-queue-not-persisted.md))なので**再起動で完全消失**。
- HR5 が要求する decision-reason が事実上残らない。

### B. `draft.assign` の監査実行者が誤り(割当先を実行者として記録)
- `DraftService.assign` は `_audit_transition(actor_id=reviewer_id)`(`api/drafts.py:164-169`)。この `reviewer_id` は
  **リクエストボディ由来の割当先**(`server.py:2009-2015`)で、署名済みプリンシパル(実際に割当を行った人)ではない。
- review 経路は署名ヘッダ由来の正しい身元を使う(`server.py:2022-2028`)が、assign だけ逆。
  → 監査ログ上「割り当てられた本人が割り当てを実行した」ことになる(SC-MFG-010 の実行者追跡を損なう)。

### C. `source_citations`(生成根拠)が HTTP create 経路で常に空
- 契約上 `POST /v1/manufacturing/drafts` は context を受け、レスポンスは `source_citations` を返す
  (`mfg-openapi.md:135,144`)。`generate_draft`/`DraftGenerator` は `context_citations` から `source_citations` を
  構築する(`generator.py:102,120`)。
- だが answer-service の create ルートは **`source_document_ids` のみ転送し `context_citations` を渡さない**
  (`server.py:1994-2002`)。→ API 経由のドラフトは `source_citations` が常に空。生成根拠の provenance が
  監査・レビュー両方で欠落。

## 提案作業(何をどう対応)

- **A:** review の `AuditLogEntry` に**冗長化安全な決定理由**(redactor 適用済みの reason、または理由カテゴリ)を
  記録。自由記述を PII 理由で監査に残さない方針なら、その旨を HR5/契約に明記して**意図的除外**として閉じる
  (どちらでも可、現状の「種別を理由扱い」は誤解を招くので是正)。`api/drafts.py:235-256` を修正。
- **B:** 実行プリンシパルを `assign_reviewer`→`DraftService.assign` までスレッドし、監査 `actor_id` を
  `principal.user_id` に。割当先 `reviewer_id` は `client_metadata` の routing target として残す。
  `app.py` の `assign_reviewer` シグネチャに actor を追加、`server.py:2009-2015` でヘッダ身元を渡す。
- **C:** create ルートで citations を解決して `context_citations` を渡す(または `source_document_ids` から
  サーバ側で citation を解決)。`server.py:1994-2002` を修正し、契約どおり `source_citations` を満たす。

## 受け入れ条件(DoD)

- [ ] 承認/却下の監査エントリから「誰が・どの決定を・(理由カテゴリ)」が追える(または除外方針を spec 明記)。
- [ ] `draft.assign` の監査 `actor_id` が実行者で、割当先は別フィールド。
- [ ] API 経由生成ドラフトの `source_citations` が空でない。
- [ ] (0012 と連動)監査・ドラフトが再起動後も保持される。

## スコープ外

- 監査エクスポート/ハッシュチェーン自体(実装済み)。永続化は [0012](0012-draft-review-queue-not-persisted.md)。

## 参照

- `src/raku_rag/manufacturing/api/drafts.py:164-169,235-256`, `src/raku_rag/manufacturing/drafts/review.py:131-133`
- `apps/answer-service/server.py:1994-2002,2009-2015,2022-2028`, `src/raku_rag/manufacturing/drafts/generator.py:102,118-124`
- spec HR5(`spec.md:362`), FR-MFG-010b(`spec.md:229`), FR-MFG-021(`spec.md:262`), `mfg-openapi.md:135,144`
