# 0049 — stg chatbot reference scope empty(系統 = QA / UX)

> Priority: **P1/High** / Status: Addressed locally / Labels: `chatbot`, `stg`, `ux`

## 背景(なぜ今)

`66f8763` を stg deploy 後、`/chatbot` が使えないとの報告を受けて Playwright で確認した。
未ログイン時の `/login?return_to=%2Fchatbot` 遷移は正常だったが、Cognito 一時ユーザーでログイン後、
チャットボット画面が「同期済みデータなし」と表示され、送信欄と参照範囲有効化ボタンが出なかった。

## どんな課題か

- チャットボットの参照範囲一覧が `AdminDataSource.last_synced_at` のみを同期済み判定に使っていた。
- stg の既存 source records は `last_synced_at: null` のものがある一方、同じ tenant/collection には文書が存在する。
- 期待挙動は、実際に文書が存在する collection は参照範囲として表示され、管理者がチャットボット利用中に設定できること。

## どこで起きたか

- 画面: `http://rakura-awsne-zv0jkvgr3ezv-1129748567.ap-northeast-1.elb.amazonaws.com/chatbot`
- API:
  - `GET /v1/admin/datasources`
  - `GET /v1/manufacturing/documents`
  - `GET /v1/chat/source-exposure-policies`
- コード:
  - `apps/web/app/components/FullSaasScreen.tsx`
- 環境: AWS stg / Cognito auth
- run id / ingestion id / correlation id: deploy run `28427770304`; Playwright temp user `codex-chatbot-1782805695@example.com` was deleted after test.
- 再現条件: stg で tenant_admin Cognito user として `/chatbot` を開く。

## 影響

- 営業デモへの影響: チャットボット画面で参照範囲を有効化できず、質問送信まで進めない。
- 本番クライアントへの影響: `data_sources.last_synced_at` が空の既存/移行データで同様にブロックされる可能性がある。
- セキュリティ、監査、データ品質、UX への影響: セキュリティ境界は API/RAG 側で維持されるが、UX 上は利用可能な文書がないように見える。

## どう解決すべきか

1. 実装方針: source の `last_synced_at` だけでなく、製造ドキュメント一覧の `collection_id/source_id` から参照範囲を復元する。
2. UI/UX 方針: 表示語は「同期済みデータ」「参照範囲」のまま維持し、有効化ボタンを表示できるようにする。
3. テスト方針: web typecheck/build と stg Playwright login smoke で、参照範囲表示と有効化ボタンを確認する。
4. 移行や運用上の注意: RAG/ACL/policy の安全条件は弱めない。チャット回答可否は引き続き policy と API 側で判定する。

## QA checklist

- [x] 再現テストがある。
- [ ] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] Playwright または API smoke で確認できる。
- [x] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 課題の根本原因が解消されている。
- regression test が追加または更新されている。
- 本番想定の UX として説明可能である。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- チャットボット policy の自動有効化。
- source/file/folder 単位の参照範囲指定。
- demo-only flag や security/safety gate の bypass。

## 参照

- GitHub Actions stg deploy run `28427770304`
- `tmp-chatbot-stg-real-login.png`
- `apps/web/app/components/FullSaasScreen.tsx`
