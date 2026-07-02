# 0047 — ファイル画面アップロードの S3 presign metadata 署名漏れ(系統 = production / upload)

> Priority: **P0 / High** / Status: **Resolved(repo-side, live smoke pending cognito deploy)** / Labels: `production`, `upload`, `files`, `aws`

## 背景(なぜ今)

本番 `/files` でフォルダ作成はできるが、ファイル選択後のアップロード取込が失敗することを
Playwright で確認した。

## どんな課題か

- 期待: `/files` から選択したファイルが S3 に PUT され、その後 `/v1/ingest` に進む。
- 実際: `/api/upload/presign` は 200 を返すが、ブラウザから S3 への `PUT` が 403 になる。
- S3 エラーは `HeadersNotSigned` で、`x-amz-meta-raku-*` ヘッダーが署名対象に入っていなかった。

## どこで起きたか

- 画面: `http://rakura-awsne-r4xgwhvpgcec-1715490950.ap-northeast-1.elb.amazonaws.com/files`
- API: `POST /api/upload/presign` → S3 presigned `PUT`
- コード: `apps/web/app/api/upload/presign/route.ts`
- 環境: AWS sales deploy, Cognito auth, document S3 bucket
- run id / ingestion id / correlation id: Playwright screenshot `/tmp/raku-rag-smoke/files-upload-prod.png`
- 再現条件: Cognito ログイン済み状態で `/files` の `アップロード` → ファイル選択 → `アップロード取込`

## 影響

- 営業デモでファイル画面の直接アップロードが使えない。
- 複数テナントの S3 prefix 設計自体は機能しているが、アップロードが ingest まで到達しない。
- エラー表示は出るが、利用者から見ると原因が不明で UX が悪い。

## どう解決すべきか

1. `getSignedUrl` で返却する `content-type` と `x-amz-meta-raku-*` を署名対象として明示する。
2. `/files` はカードではなく list view にして、アップロード/詳細/フォルダ操作が崩れない配置にする。
3. 契約テストで metadata header の `signableHeaders` / `unhoistableHeaders` を固定する。
4. 本番デプロイ後、Playwright で `/api/upload/presign` 200、S3 `PUT` 200、`/v1/ingest` 成功または queued を確認する。

## QA checklist

- [x] 再現テストがある。
- [ ] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- S3 `HeadersNotSigned` が発生しない。
- `/files` から root/folder のどちらにもアップロードできる。
- `/files` の見た目が list view になり、行のボタンが崩れない。
- 既存の認証、tenant prefix、ACL、安全ゲートを弱めていない。

## スコープ外

- 既存 Cognito ユーザーのパスワード変更。
- 署名検証や tenant prefix の bypass。
- サブフォルダ対応。

## 参照

- `apps/web/app/api/upload/presign/route.ts`
- `apps/web/app/components/FullSaasScreen.tsx`
- `apps/web/app/globals.css`
- AWS SDK `@aws-sdk/s3-request-presigner` `unhoistableHeaders` / `signableHeaders`

## 対応メモ

- 署名修正は `bb61c4f fix(web): sign file upload metadata headers` で実装済み
  (`getSignedUrl` に `signableHeaders`/`unhoistableHeaders` を明示)。
- 2026-07-02: 契約テスト `tests/contract/test_upload_presign_route.py` で
  signableHeaders / unhoistableHeaders / tenant prefix / 登録先行(0045)をソース固定。
- `/files` は list view 化済み(`fb-list-row`)。
- 残: cognito デプロイ後の live smoke(presign 200 → S3 PUT 200 → ingest)。手順は
  `docs/deploy/cognito-stg-runbook.md` §3。
