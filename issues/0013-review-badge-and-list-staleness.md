# 0013 — レビューバッジ/一覧の陳腐化・トリアージ/ページング欠如(系統 ①)

> Priority: **P2 / Medium** / Status: Open / Labels: `frontend`, `review-queue`, `ux`, `staleness`

## 背景(なぜ今)

`GET /v1/manufacturing/drafts`(list)は**全層で実装済み**(Python `api/drafts.py:120`→answer-service
`server.py:1591`→NestJS `controller.ts:220`→client `api-client.ts:224`、`status`/`reviewer_id` フィルタ対応)。
しかしフロントは list 実装前の**仮実装の残骸**を引きずっており、バッジ・コメント・トリアージが未追従。

## 現状(根拠)

- **バッジが定数**:`apps/web/lib/full-saas.ts:35` `REVIEW_BADGE_COUNT = 2`(ハードコード)。
  コメント `:33-34` 自身が「`GET /v1/manufacturing/drafts` ができたら差し替え」と書くが、その endpoint は既に存在。
  `Sidebar.tsx:75-78` がこの定数をそのまま描画(`aria-label="未レビュー 2 件"`)。0 件でも 50 件でも常に「2」。
- **陳腐化コメント**:`apps/web/lib/drafts.ts:1-5`「list endpoint はまだ無い」も古い(実際は server list を使用、
  localStorage は catch フォールバックのみ:`FullSaasScreen.tsx:2208,2220`)。
- **パネル内カウントが全件**:`FullSaasScreen.tsx:2271` の `{drafts.length}` は status 無関係の全件
  (approved/rejected/archived 込み)。「キュー(=未処理)」の意味と乖離。
- **トリアージ無し**:list は `status`/`reviewer_id` で絞れるのに UI は無指定で全件取得(`:2208`)。
  「pending のみ」「自分担当」「並び替え」「優先度/SLA」が無く、終了済みドラフトが現役と混在(newest-first のみ)。
- **ページング無し**:`api/drafts.py:120-138`/`controller.ts:220-231`/`api-client.ts:224-237`/UI いずれも
  limit/offset を持たず、テナント全ドラフトを一括取得・一括 map(`:2279`)。

## 提案作業(何をどう対応)

1. **バッジをライブ化**:`Sidebar`(または小さな client hook)で `manufacturingListDrafts(token, {status})` を
   叩き、未処理件数 = `status ∈ {draft, in_review}` を算出してバッジへ。0 件は非表示。`REVIEW_BADGE_COUNT` 定数を撤去。
   ※ Sidebar は全画面共通なので、未認証/失敗時は 0 にフォールバック(エラーを出さない)。
2. **パネル内カウントの意味付け**:既定で pending のみ表示、または「全 N 件 / 未処理 M 件」と明示。
3. **トリアージ UI**:`reloadDrafts`(`:2205`)に `{status, reviewerId}` を渡し、フィルタチップ
   (未処理 / 自分担当 / 全件)と並び替えを追加。既定は「未処理」。
4. **ページング**:`DraftService.list`→app→controller→client に `limit/offset`(または keyset)を通し、
   UI はページ送り/仮想化。`audit-events` が既に limit/offset を持つので踏襲。
5. **陳腐化コメント除去**:`lib/drafts.ts:1-5` と `full-saas.ts:33-34` を現状(list は実装済み)に更新。
   localStorage は「オフライン時のヒント」に降格(SSOT は server)、用途をコメントで明記。

## 受け入れ条件(DoD)

- [ ] バッジが実際の未処理件数に一致し、0 件で消える。
- [ ] 既定で未処理ドラフトのみ、フィルタで「自分担当/全件」に切替できる。
- [ ] 大量ドラフトでも一括取得・一括描画にならない(ページング)。
- [ ] 古いコメント(list 未実装前提)が残っていない。

## スコープ外

- list 失敗時のエラー/ローディング表示と localStorage 依存の是正は [0015](0015-review-detail-ux-state-machine-mismatch.md) / 永続化は [0012](0012-draft-review-queue-not-persisted.md)。

## 参照

- `apps/web/lib/full-saas.ts:32-35`, `apps/web/app/components/Sidebar.tsx:75-78`, `apps/web/lib/drafts.ts:1-5`
- `apps/web/app/components/FullSaasScreen.tsx:2205-2222,2271,2279`, `apps/web/lib/api-client.ts:224-237`
- `src/raku_rag/manufacturing/api/drafts.py:120-138`, `apps/api/src/manufacturing/manufacturing.controller.ts:220-231`
