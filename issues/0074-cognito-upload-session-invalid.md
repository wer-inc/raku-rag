# 0074 — Cognito file upload reports invalid session without recoverable auth path(系統 = production / upload-auth)

> Priority: **P0/High** / Status: Open / Labels: `production`, `upload`, `cognito`, `ux`, `stg`

## 背景(なぜ今)

stg の `/files` から file upload を実行したユーザーが
`Cognito session is invalid; sign in again` に遭遇した。直近の stg 確認では
`POST /api/upload/presign` が認証なしで `Cognito session is missing; sign in again`、
不正 JWT で `Cognito session is invalid; sign in again` を返すことを確認した。

## どんな課題か

- 期待: Cognito ログイン済みユーザーが `/files` からアップロードすると、
  presign -> S3 PUT -> `/v1/ingest` まで進む。セッションが無効な場合は自動的に再ログイン導線へ
  誘導され、原因が「期限切れ」「古い user pool/client」「tenant 未割当」のどれか分かる。
- 実際: upload presign は `/v1/whoami` が non-2xx を返した理由をすべて
  `Cognito session is invalid; sign in again` に丸める。UI は通常画面を表示できているように見えるため、
  ユーザーには upload だけ壊れたように見える。
- ブラウザ側の `loadCognitoToken()` は JWT の `exp` だけを見ており、現在の
  `auth-config` の issuer/client_id や `custom:tenant_id` の有無を検証しない。

## どこで起きたか

- 画面: `/files`
- API: `POST /api/upload/presign` -> internal self-check `GET /v1/whoami`
- コード:
  - `apps/web/app/api/upload/presign/route.ts`
  - `apps/web/lib/session.ts`
  - `apps/api/src/auth/cognito.ts`
- 環境: stg CloudFront `https://dgjq9rlehwxl7.cloudfront.net`, Cognito auth
- run id / ingestion id / correlation id:
  - stg probe 2026-07-04:
    - `GET /api/auth-config` -> Cognito config present
    - `GET /v1/whoami` no auth -> 401 `missing bearer token`
    - `POST /api/upload/presign` no auth -> 401 `Cognito session is missing; sign in again`
    - `POST /api/upload/presign` invalid JWT -> 401 `Cognito session is invalid; sign in again`
- 再現条件:
  - Stale Cognito token from an older stg user pool/client remains in browser storage, or
  - Cognito user/token lacks signed `custom:tenant_id`, or
  - Client falls back from ID token to an access token that API cannot map to tenant.

## 影響

- 営業デモへの影響: file upload の初回体験が詰まり、根拠文書レビューまで到達しない。
- 本番クライアントへの影響: セッション更新・テナント割当ミス・再deploy後の stale token が
  「upload が壊れた」ように見える。
- セキュリティ/監査: API 側が tenant claim を要求して fail-closed している点は正しい。
  問題は client/session UX と presign 診断が粗いこと。
- データ品質: upload が ingest されず、レビュー待ち文書が作られない。

## どう解決すべきか

1. 実装方針。
   - Browser session は保存済み Cognito token を `exp` だけでなく、現在の
     `/api/auth-config` の `cognito_issuer` / `cognito_client_id` / `token_use` /
     `custom:tenant_id` で検証する。
   - App API に送る bearer token を ID token に統一するか、access token でも tenant を解決できる
     server-side exchange を実装する。現状の access-token fallback は tenant claim 不足で失敗し得る。
   - API/presign が 401 を返したら `clearSessionToken()` して
     `/login?return_to=<current>` へ誘導する共通 auth failure handler を入れる。
   - `/api/upload/presign` は `/v1/whoami` の失敗を丸めず、少なくとも
     `missing_session` / `invalid_session` / `missing_tenant_claim` / `session_mismatch`
     の client-safe error code を返す。
2. UI/UX 方針。
   - upload 失敗欄に raw 英語エラーを出さず、「ログイン情報を更新してください」「テナント割当がありません」
     など行動可能な日本語にする。
   - 再ログインボタンを同じエラー領域に出す。
3. テスト方針。
   - `apps/web/lib/session.ts` の token validation unit test を追加する。
   - presign route test で stale issuer/client, missing tenant, invalid JWT の応答を固定する。
   - Cognito auth e2e で ID token happy path と access-token-only failure/handling を明示する。
4. 移行や運用上の注意。
   - 直近 stg の応急対応はブラウザ storage の古い `raku.cognito.*` を消して再ログイン。
   - Cognito ユーザーには `custom:tenant_id=demo` と必要 group/role を必ず付ける。
   - stg deploy 後の smoke に `/files` upload happy path を必須化する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- Stale Cognito token は upload 前に検出され、再ログイン導線に進む。
- `custom:tenant_id` がない Cognito user は upload 以前に明確な管理者向けエラーになる。
- Valid Cognito ID token では `/api/upload/presign` が 200 を返し、S3 PUT へ進む。
- access token だけで tenant を確定できない状態を silent fallback しない。
- 既存の tenant/ACL 境界、upload provenance、one-time upload_id 消費を弱めていない。

## スコープ外

- 認証なし upload の許可。
- `custom:tenant_id` がないユーザーを暗黙に `demo` tenant へ入れること。
- presign/ingest の tenant prefix 検証や upload_id provenance の緩和。

## 参照

- `apps/web/app/api/upload/presign/route.ts`
- `apps/web/lib/session.ts`
- `apps/api/src/auth/cognito.ts`
- `docs/deploy/cognito-stg-runbook.md`
- `issues/0041-aws-upload-sink-disabled.md`
- `issues/0047-files-upload-presign-unsigned-metadata.md`
