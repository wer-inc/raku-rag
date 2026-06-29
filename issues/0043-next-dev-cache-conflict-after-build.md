# 0043 — Next dev 稼働中に web build を走らせると .next キャッシュ不整合で 500 になる(系統 = qa / developer-experience)

> Priority: **P3 / Low** / Status: Open / Labels: `qa`, `developer-experience`, `frontend`

## 背景(なぜ今)

`/sources/new` の UI 変更後、`npm run build --workspace @raku-rag/web` とローカル
Next dev サーバーの HTTP smoke を同じ作業中に実行したところ、dev サーバーが
React Client Manifest / webpack runtime の不整合で 500 を返した。

## どんな課題か

- 期待挙動: build 後も dev サーバーの確認 URL が安定して 200 を返す、または手順上の注意が明確。
- 実際の挙動: dev サーバー稼働中に build が `.next` を更新すると、dev 側が古い manifest/runtime を参照し 500 になる。
- `rm -rf apps/web/.next` 後に dev サーバーを再起動すると復旧するため、アプリ実装ではなく生成キャッシュ競合の可能性が高い。

## どこで起きたか

- 画面: `/sources/new`
- API: なし
- コード: `apps/web/.next` 生成物
- 環境: local Next.js dev server (`npm run dev --workspace @raku-rag/web -- --hostname 0.0.0.0 --port 3005`)
- run id / ingestion id / correlation id: なし
- 再現条件: dev サーバー稼働中に `npm run build --workspace @raku-rag/web` を実行し、その後 `curl -I http://localhost:3005/sources/new`

## 影響

- 営業デモへの影響: ローカルデモ中に build と dev 確認を混在させると、画面が 500 になり混乱する。
- 本番クライアントへの影響: 本番 build 自体は成功しており、現時点では直接影響なし。
- セキュリティ、監査、データ品質、UX への影響: なし。ただし QA 手順の信頼性に影響する。

## どう解決すべきか

1. 実装方針: dev と build の `.next` 生成物を同時に触らない運用にする。必要なら smoke script で dev 再起動前に `.next` を削除する。
2. UI/UX 方針: なし。
3. テスト方針: frontend smoke 手順に「build 後は dev を再起動してから HTTP smoke」を明記する。
4. 移行や運用上の注意: 本番ビルド確認後にローカル URL を渡す場合は、dev サーバーを再起動して 200 を確認する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- frontend ローカル確認手順で build/dev キャッシュ競合が起きない。
- build 後の `/sources/new` smoke が 200 になることを確認できる。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- Next.js 自体の内部 manifest/runtime 問題の修正。
- security/safety gate の緩和。
- 本番デプロイ手順の変更。

## 参照

- `apps/web/package.json`
- `apps/web/.next` 生成物
- 2026-06-29 local smoke: `curl -I http://localhost:3005/sources/new` が build 後に 500、`.next` 削除と dev 再起動後に 200。
