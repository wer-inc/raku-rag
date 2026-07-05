# 0077 — presign 検証の自己 fetch が CloudFront の http→https リダイレクトで Authorization を落とし、アップロードが session_mismatch になる(系統 = web / upload / cognito）

> Priority: **P0/High** / Status: Fixed / Labels: `web`, `upload`, `cognito`, `stg`, `infra`

## 背景(なぜ今)

stg CloudFront `https://dgjq9rlehwxl7.cloudfront.net/files` で「ファイルアップロードしても何も起きない」
と報告された。0074–0076 の認証復旧 UX を出した後の再発で、実際には**アップロード presign 自体が
CloudFront 経由だと必ず失敗**していた(認証復旧ループの真因もこれ)。

## どんな課題か

- 期待: ログイン済みユーザーが `/files` でファイルを選び「アップロード取込」すると presign が成功し、
  S3 PUT → ingest まで進む。
- 実際: `POST /api/upload/presign` が **CloudFront 経由だと 401 `session_mismatch`**、ALB 直だと 200。
  同じトークンで `/v1/whoami` は 200 を返すのに、presign だけが session_mismatch を返していた。

## どこで起きたか

- 画面: `/files`(アップロードパネル)
- API: `POST /api/upload/presign`(Next.js route)→ 内部で `GET /v1/whoami` / `POST /v1/uploads`
- コード: `apps/web/app/api/upload/presign/route.ts`(`publicOrigin` / `assertAppSession`)
- 環境: stg CloudFront `E3C90PNWLG7X8Q`(`dgjq9rlehwxl7.cloudfront.net`), ALB `RakuRa-AwsNe-…`
- 再現条件: 有効な Cognito id トークンで CloudFront 経由に `POST /api/upload/presign`。

## 真因(実測で確定)

1. `assertAppSession` は fail-closed で `${publicOrigin(req)}/v1/whoami` を**サーバ側から自己 fetch**して
   セッションを再検証する。
2. CloudFront の origin-request policy は **Managed-AllViewer**(`216adef6-…`)。CF→ALB は http なので、
   web コンテナが受け取る `host` は `dgjq9rlehwxl7.cloudfront.net`、`x-forwarded-proto` は **http**。
   → `publicOrigin` は `http://dgjq9rlehwxl7.cloudfront.net` を組み立てる。
3. CloudFront は `redirect-to-https` なので `http://…/v1/whoami` は **301 → https**。
4. `fetch()` はリダイレクト追従時に **http→https のスキーム変更(=別オリジン)で Authorization ヘッダを
   除去**する。結果 whoami はトークン無しで届き **401**。
5. `assertAppSession` は `!res.ok`(401, 非403)→ `classifyBearerToken` → トークンは exp/issuer/client/
   tenant すべて正当なので最終フォールバック **`session_mismatch`** を返す。
6. ブラウザ側はこれを「ログイン設定が変更されました」トースト＋再ログイン誘導として扱い、
   再ログインしても presign が同じ 401 を返すため、体感は「何も起きない」/ 認証ループになる。

実測: presign via ALB=**200**(正しい presigned URL), presign via CloudFront=**401 session_mismatch**,
`http://CF/v1/whoami`=**301→https**, `https://CF/v1/whoami`(auth有)=**200** / (auth無)=**401**。

## 影響

- 営業デモ/本番: CloudFront 経由の**全ユーザーでファイルアップロードが機能しない**(S3/バケット/CORS/
  API 認証はすべて正常なのに presign 段で落ちる)。
- 認証復旧 UX(0074–0076): 症状(ループ)を緩和していたが真因はこれ。fail-closed 自体は正しい。
- セキュリティ/監査: 弱化なし。tenant は principal 由来のまま。

## どう解決したか

1. `publicOrigin` を修正: 公開エッジは常に HTTPS(CloudFront、またはカスタムドメインの ALB ACM)。
   直 ALB DNS(`*.elb.amazonaws.com`)/ localhost のみ http を維持し、それ以外は **https を強制**。
   → 自己 fetch が 301 を踏まず、Authorization が保持され whoami 200。
2. `RAKU_UPLOAD_VERIFY_ORIGIN` / `RAKU_INTERNAL_API_ORIGIN` の明示 override に対応(将来、内部オリジンで
   公開往復自体を回避できるようにする布石)。
3. regression: `tests/contract/test_upload_presign_route.py` に https 強制 + override のソースマーカーを追加。

## QA checklist

- [x] 再現テストがある(source contract)。
- [x] 正常系が確認できる(ALB 直 presign 200 / 修正後 CloudFront presign 200 を live 実測)。
- [x] 失敗時の表示/応答が確認できる(修正前 401 session_mismatch を live 実測)。
- [x] tenant/ACL 境界を越えない(tenant は principal 由来)。
- [x] security/safety gate を弱めていない(fail-closed 維持)。
- [x] AWS stg live smoke で確認(real Cognito token で presign→PUT→ingest)。

## 受け入れ条件(DoD)

- CloudFront 経由の `POST /api/upload/presign` が有効トークンで 200 と presigned URL を返す。
- `/files` からのアップロードが presign→S3 PUT→ingest まで通る。
- 直 ALB/localhost 経路(smoke/dev)を壊さない。
- regression test が追加されている。

## スコープ外

- CloudFront の origin-request policy / redirect-to-https の変更。
- 内部 API オリジン env の CDK 注入(override 対応のみ実装、注入は follow-up)。

## 参照

- `apps/web/app/api/upload/presign/route.ts`
- `tests/contract/test_upload_presign_route.py`
- `issues/0074-cognito-upload-session-invalid.md` / `issues/0076-login-return-to-stale-token-bounce.md`
