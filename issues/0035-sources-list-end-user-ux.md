# 0035 — ソース一覧の情報設計がエンドユーザー目線で重い(系統 = UX / information-architecture)

> Priority: **P2/Medium** / Status: In Progress / Labels: `ux`, `sources`, `information-architecture`

## 背景(なぜ今)

AWS stg の `/sources/list` を確認したところ、データソースの同期状態を扱う画面としては機能しているが、実際の利用者が「どのソースが使えるか」「何をすべきか」を判断するには、内部用語や管理者向け項目が前面に出ている。

## どんな課題か

- 一覧列が `ソース / 種別 / ステータス / 文書数 / 最終同期 / コレクション / 承認内訳` の7列で、役割が近い情報が横並びになっている。
- `種別`, `コレクション`, `changed_count` 相当の文書数は、一般利用者には判断材料として弱い。
- `ステータス` が同期状態なのか利用可能状態なのか分かりにくい。
- `承認内訳` は重要だが、次に何をすべきかへの導線がない。
- データ量が増えた時の pagination / 検索 / フィルタ / ソートがなく、運用画面として詰まりやすい。
- モバイルでは横スクロール前提になり、主要情報のスキャン性が落ちる。
- UIUX Pro Max の mock visual check で、`partially_succeeded` が「確認が必要」ではなく「同期中」と表示されることを確認した。これは処理中ではなく一部失敗/要確認の終端状態なので、ユーザーに再同期・レビューの判断を促す表示が必要。

## どこで起きたか

- 画面: `/sources/list`
- API: `GET /v1/admin/datasources`, `GET /v1/manufacturing/sources/{source_id}/sync-status`
- コード: `apps/web/app/components/FullSaasScreen.tsx` (`SourceListBody`)
- コード: `apps/web/app/globals.css` (`standalone-table-*`)
- 環境: AWS stg, `develop@22351a6`
- run id / ingestion id / correlation id: なし
- 再現条件: 複数データソースを作成し、同期・承認状態を一覧で確認する。

## 影響

- 営業デモへの影響: データ接続後の運用イメージが伝わりにくい。
- 本番クライアントへの影響: 運用者が「未同期」「承認待ち」「再同期が必要」の判断をしにくい。
- セキュリティ、監査、データ品質、UX への影響: 誤って古い/未承認データを放置する運用リスクがある。ACL や承認ルール自体は変えない。

## どう解決すべきか

1. 実装方針: 一覧をカード寄りの業務リストに再設計し、主要列を `名前`, `利用状態`, `最終同期`, `文書`, `次の操作` に絞る。
2. UI/UX 方針: `コレクション`, `source_id`, `同期 run`, `内部ステータス`, `種別の raw 値` は詳細画面または管理者向け展開に移す。
3. テスト方針: データソース多数件、同期中、失敗、承認待ちあり、未同期、空状態での表示を確認する。
4. 移行や運用上の注意: API 互換は維持し、表示整理のみで承認ポリシーや ACL を変更しない。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 一覧で「使える」「確認が必要」「同期が必要」「失敗」の状態が一目で分かる。
- `partially_succeeded` は「同期中」ではなく「確認が必要」として表示される。
- 10件超でも検索・フィルタ・pagination で操作できる。
- 承認待ちがあるソースから `根拠文書レビュー` に直接移動できる。
- 同期失敗ソースから詳細画面または再同期操作へ迷わず移動できる。
- エンドユーザー向け表示と管理者/デバッグ向け表示が分離されている。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- API の破壊的変更。
- 自動承認や承認ポリシー変更。
- ソース同期エンジンの作り直し。
- 本格的なスケジューラ実装。

## 参照

- `/sources/list`
- `apps/web/app/components/FullSaasScreen.tsx`
- `apps/web/app/globals.css`
- `issues/0034-datasource-resync-ux.md`
