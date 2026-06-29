# 0034 — データソース再同期導線が分かりにくい(系統 = UX / datasource-sync)

> Priority: **P2/Medium** / Status: Open / Labels: `ux`, `datasource-sync`

## 背景(なぜ今)

AWS stg 環境でデータソース同期後、元データソース側のファイルやページが更新された場合に、ユーザーがどこから再同期すればよいか質問が出た。実装上はソース詳細画面から手動同期できるが、導線と文言が直感的ではない。

## どんな課題か

- ユーザーが「データソースを更新した後、再同期したい」時に、`Documents` / `ソース` / `データソース` / `同期状態` のどこを操作すべきか迷う。
- 期待挙動: データソース一覧から対象ソースを選び、明確な `再同期` 操作で更新分を取り込めることが分かる。
- 実際の挙動: `/sources/{source_id}` の `同期を依頼` ボタンで再同期できるが、初回同期なのか再同期なのか、更新分だけを見るのかが分かりにくい。
- `sync_schedule` 入力は保存されるが、ユーザーに自動同期の有効状態として説明できる UI になっていない。

## どこで起きたか

- 画面: `/sources/list`, `/sources/{source_id}`, `/sources/new`, `/documents`
- API: `POST /v1/admin/sources/{source_id}/sync`, `GET /v1/admin/sources/{source_id}/sync-status`
- コード: `apps/web/app/components/FullSaasScreen.tsx` (`SourceListBody`, `SourceDetailBody`, `AddSourceBody`)
- コード: `apps/web/lib/api-client.ts` (`adminSourceSync`)
- コード: `src/raku_rag/services/source_sync.py` (`request_source_sync`, `execute_source_sync`)
- 環境: AWS stg, `develop@22351a6`
- run id / ingestion id / correlation id: なし
- 再現条件: ソース作成・初回同期後、元データソース側を更新し、画面から再同期方法を探す。

## 影響

- 営業デモへの影響: データ更新後の「RAG が最新情報に追従できる」説明が弱くなる。
- 本番クライアントへの影響: 運用者が不要な新規ソース作成やファイル再アップロードを行う可能性がある。
- セキュリティ、監査、データ品質、UX への影響: 再同期操作自体は監査可能だが、誤操作や古い文書を参照し続ける運用リスクがある。

## どう解決すべきか

1. 実装方針: 既存の `POST /admin/sources/{source_id}/sync` を使い、対象ソース詳細に明確な再同期操作を置く。
2. UI/UX 方針: `同期を依頼` を `今すぐ再同期` などに変更し、最終同期日時・変更数・承認待ち数・次の行き先を同じ面に表示する。
3. テスト方針: 既存ソースの詳細画面で再同期ボタンが表示され、API に `reason=manual_refresh` が送られることを確認する。
4. 移行や運用上の注意: 承認ポリシー(`review_required` / `trusted`)の意味は変えない。再同期で新規・更新文書がどの承認状態になるかを UI に明示する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 既存データソースの詳細画面から、ユーザーが迷わず手動再同期できる。
- 再同期後の遷移先または次アクションとして、`根拠文書レビュー` / `ナレッジ文書` が分かる。
- 再同期結果に `観測数`, `変更数`, `削除数`, `失敗数`, `最終同期` が表示される。
- `review_required` ソースは更新分が承認待ちに入ること、`trusted` ソースは承認済み扱いになることが明示される。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- 承認ポリシーの意味変更。
- 自動承認の追加。
- セキュリティや tenant 境界の bypass。
- 本課題内での本格的なスケジューラ実装。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx`
- `apps/web/lib/api-client.ts`
- `src/raku_rag/services/source_sync.py`
- `apps/api/src/admin/jobs.controller.ts`
