# 0039 — ドキュメント一覧が運用ライブラリとして判断しづらい(系統 = ux / documents / information-architecture)

> Priority: **P2/Medium** / Status: In Progress / Labels: `ux`, `documents`, `information-architecture`, `review`

## 背景(なぜ今)

UI/UX Pro Max 監査で、`/documents` はテナント内ドキュメントを表示できている一方、SaaS の運用画面として
「どの文書を確認すべきか」「何が正式根拠として使えるか」「次に何をするか」を判断するには弱いことが分かった。

`/sources/list` は同期状態、承認待ち件数、次アクションを持つ業務リストへ改善されつつあるが、`/documents` は
まだ raw ID 中心の汎用テーブルに近く、文書量が増えたときの検索・絞り込み・優先順位付けも不足している。

## どんな課題か

- 一覧の主表示が `document_id` で、文書名、種別、ソース、承認状態、発効日、鮮度の関係が読み取りにくい。
- `承認待ち`、`旧版`、`ドラフト`、`承認済み` の状態は表示されるが、どれをレビューすべきか・正式根拠として使えるかが次アクションにつながらない。
- 検索、承認状態フィルタ、ソース/種別フィルタ、ページング、並び替えがなく、文書が増えると運用一覧として詰まる。
- `最近アップロードしたドキュメント` はこのブラウザの控えとテナント全体一覧が分かれており、正式反映前後の関係が初見では分かりにくい。
- `この控えを消去` はローカル控えのみの削除だが、赤い destructive ボタンに見え、テナント文書削除と混同しやすい。
- 詳細画面も JSON メタデータ編集・処理状態 JSON が前面にあり、業務レビュア向け情報と診断情報の分離が不十分。

期待挙動:

- 文書一覧で、正式根拠として使える文書、レビュー待ち、旧版、処理失敗/未処理がすぐ分かる。
- 承認待ち文書から `根拠文書レビュー` へ自然に移動できる。
- 文書量が増えても検索・フィルタ・ページングで目的の文書にたどり着ける。
- 直近アップロードとテナント全体の正式一覧が同じ文書一覧の中で扱われ、実装都合の別枠に見えない。

実際の挙動:

- `/documents` は `DataTable` で `文書 / 種別 / 承認状態 / 発効日 / ソース / コレクション` を並べるだけで、
  検索・絞り込み・ページング・次アクションがない。
- 文書 ID とコレクションなど内部寄りの値が主表示になり、文書レビューや正式根拠化の判断が画面内で閉じない。

## どこで起きたか

- 画面: `/documents`
- 画面: `/documents/:documentId`
- API: `GET /v1/manufacturing/documents`, `GET /v1/admin/documents/:document_id/processing-status`
- コード: `apps/web/app/components/FullSaasScreen.tsx` (`DocumentListBody`, `DocumentDetailBody`, `DataTable`)
- コード: `apps/web/app/globals.css` (`screen-section`, `data-table`, document/detail related styles)
- 環境: local UI/UX code review
- run id / ingestion id / correlation id: なし
- 再現条件:
  1. `/documents` を開く。
  2. 複数の承認状態・ソース・文書種別が混在する一覧を確認する。
  3. どの文書をレビュー/正式根拠化/旧版確認すべきかを UI だけで判断する。

## 影響

- 営業デモへの影響: 取り込んだ文書が見えるだけに留まり、運用できるナレッジライブラリとしての完成度が伝わりにくい。
- 本番クライアントへの影響: 文書量が増えると承認待ちや旧版文書を見落としやすく、レビュー滞留が起きる。
- セキュリティ、監査、データ品質、UX への影響: ACL/tenant 境界自体は変えないが、未承認/旧版文書の放置で高リスク回答が保留されやすくなる。

## どう解決すべきか

1. 実装方針:
   - `/documents` を業務リスト化し、検索、承認状態フィルタ、ソース/種別フィルタ、ページングを追加する。
   - 承認待ち行には `根拠文書レビューへ`、旧版行には `旧版の扱いを確認`、処理失敗行には `処理状態を見る` を出す。
   - raw `document_id` / `collection_id` / processing JSON は既定表示から下げ、詳細または診断セクションへ移す。
2. UI/UX 方針:
   - 主表示は「文書名または分かるタイトル」「正式根拠としての状態」「発効/鮮度」「ソース」「次の操作」に寄せる。
   - 直近アップロードは別セクションにせず、同じ文書一覧へ `直近アップロード（一覧反映待ち）` として統合する。
   - ローカル履歴の削除は `この端末の履歴だけ消去` と明記し、テナント文書削除ではないことを文言で示す。
   - 詳細画面はレビュア向け概要、承認/根拠状態、ファイル/引用プレビュー、診断情報を分ける。
3. テスト方針:
   - Playwright で承認待ち、承認済み、旧版、空状態、多数件の表示とフィルタを確認する。
   - `この控えを消去` がテナント文書削除ではないことを UI テストまたは文言 snapshot で固定する。
4. 移行や運用上の注意:
   - API shape と ACL/tenant/safety gate は変更しない。
   - 文書削除や旧版復旧の方針は既存 issue と連動し、UI 表示だけで安全ルールを緩めない。

## QA checklist

- [ ] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 文書一覧で正式根拠、承認待ち、旧版、処理異常が一目で区別できる。
- 検索・フィルタ・ページングにより多数文書でも運用できる。
- 承認待ち文書から根拠文書レビューへ移動できる。
- 直近アップロードとテナント文書一覧が分断されず、一覧内で状態として理解できる。
- 詳細画面で業務情報と診断情報が分離されている。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- 文書承認ワークフローの安全ルール緩和。
- `obsolete` の復旧設計そのもの。これは `issues/0021-obsolete-action-recovery-ux.md` で扱う。
- 承認ルール編集 API の実装。これは `issues/0014-approval-rules-settings-non-functional.md` と連動。
- AI ドラフトの publish/知識化経路。これは `issues/0019-no-publish-path-after-approval.md` で扱う。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx:253`
- `apps/web/app/components/FullSaasScreen.tsx:4732`
- `apps/web/app/components/FullSaasScreen.tsx:4783`
- `apps/web/app/components/FullSaasScreen.tsx:4816`
- 2026-06-29 partial fix: `取込直後の控え` セクションを廃止し、`直近アップロード` フィルタと
  一覧内の `直近アップロード（一覧反映待ち）` 表示へ統合。
- `specs/full-saas/screens.manifest.json:204`
- `specs/full-saas/gaps.md:15`
- `issues/0014-approval-rules-settings-non-functional.md`
- `issues/0015-review-detail-ux-state-machine-mismatch.md`
- `issues/0021-obsolete-action-recovery-ux.md`
- `issues/0022-approval-flow-information-architecture.md`
