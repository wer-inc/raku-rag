# 0038 — 接続済みソース一覧の行アクション overflow (系統 = ux / sources-list)

> Priority: **P2/Medium** / Status: Open / Labels: `ux`, `sources-list`, `frontend`

## 背景(なぜ今)

sales 環境へデプロイ後、`/sources/list` の動作確認スクリーンショットで、1行目だけ操作ボタンが3つ並び、行末が右端へ押し出されて見えることをユーザーが指摘した。

## どんな課題か

- 承認待ちがあるソースでは `レビューへ`、`再同期を依頼`、`詳細` の3ボタンが同じ操作列に並ぶ。
- 操作列が広がり、テーブル風リストの右端が窮屈または欠けて見える。
- 期待挙動は、重要操作を維持しつつ行の横幅を壊さないこと。

## どこで起きたか

- 画面: `/sources/list`
- API: なし
- コード: `apps/web/app/components/FullSaasScreen.tsx`, `apps/web/app/globals.css`
- 環境: sales deploy `28358970865`
- run id / ingestion id / correlation id: GitHub Actions run `28358970865`
- 再現条件: 承認待ち文書を持つ登録済みソースがあり、行アクションが3つ表示される。

## 影響

- 営業デモで画面が壊れている印象を与える。
- end user がどの操作を押すべきか迷いやすくなる。
- セキュリティ、監査、データ品質への直接影響はない。

## どう解決すべきか

1. `詳細` は独立ボタンではなくソース名リンクへ寄せ、行末の操作数を最大2つにする。
2. 操作列は固定最小幅と折り返しを持たせ、リスト全体を右に押し出さない。
3. Playwright で pending review + resync の同時表示を確認する。
4. 既存 API/ACL/承認状態の意味は変えない。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 行末のアクションが3ボタンで横 overflow しない。
- ソース詳細への導線が失われていない。
- モバイルでも操作が読みやすく折り返される。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- 行アクションメニュー化やドロップダウン導入。
- 承認フロー、同期 API、ACL、テナント分離の仕様変更。
- demo-only の表示分岐。

## 参照

- GitHub Actions deploy run: `28358970865`
- Screenshot: `/tmp/raku-deploy-sources-list.png`
