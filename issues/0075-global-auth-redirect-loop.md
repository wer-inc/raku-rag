# 0075 — 共通認証エラー処理が再ログインループを作り得る(系統 = web / cognito-ux)

> Priority: **P0/High** / Status: Open / Labels: `web`, `cognito`, `ux`, `auth`, `stg`

## 背景(なぜ今)

stg CloudFront `https://dgjq9rlehwxl7.cloudfront.net/files` のファイルアップロードで、
ログイン画面へ遷移したあと `/files` に戻り、同じ認証エラーで再びログイン画面へ遷移する
ループが確認された。upload 固有のループは `fe86592` で防止したが、調査中に共通 load handler
にも同型の処理があることを確認した。

## どんな課題か

- 期待: API が 401 を返した場合でも、期限切れ・セッション不一致・tenant 未設定・権限不足・
  API/Cognito 設定不一致を区別し、再ログインで回復しない状態では画面上で止めて管理者確認を促す。
- 実際: `useLoad()` は `isAuthError()` に一致するエラーをすべて `clearSessionToken()` +
  `/login?return_to=...` に流す。ログイン後に同じ API 401 が続く場合、upload と同じループを
  他画面でも再現し得る。
- `api-client.ts` は API error body の `error` / `error_code` を落とし、`message` か `HTTP <status>`
  に丸める。そのため client 側は原因別 recovery をしづらい。
- `isAuthError()` は文字列正規表現で `session|token|auth|jwt|cognito` を拾うため、
  401 以外の設定/接続/ドメインエラーでも誤ってセッションを消す可能性がある。

## どこで起きたか

- 画面:
  - `/home`
  - `/sources`
  - `/operations`
  - `/reviews`
  - `/admin/*` 相当の設定パネル
  - 電話RAG / 品質 / 監査 / ACL / provider policy / retrieval / logging privacy など
- API:
  - `GET/POST /v1/*` 全般
- コード:
  - `apps/web/app/components/FullSaasScreen.tsx`
    - `isAuthError()`
    - `redirectToLoginAfterAuthError()`
    - `useLoad()`
    - `runWithToken()` call sites
  - `apps/web/lib/api-client.ts`
    - `jsonOrThrow()`
- 環境:
  - stg CloudFront `https://dgjq9rlehwxl7.cloudfront.net`
- run id / ingestion id / correlation id:
  - なし。調査は source-level + unauthenticated/invalid-token probe。
- 再現条件:
  - Browser session は claim validation 上 OK だが、API が Cognito/JWKS/client/issuer/tenant 設定不一致で
    401 を返す。
  - または API が client-safe `error_code` を返しても web common client がそれを保持しない。

## 影響

- 営業デモへの影響: upload 以外の画面でも「ログインしても戻される」体験になり得る。
- 本番クライアントへの影響: Cognito 設定変更、user pool/client 差し替え、tenant claim 設定漏れ時に
  原因が管理者へ伝わりにくい。
- セキュリティ/監査: API fail-closed 自体は正しい。問題は recovery UX と診断情報の失われ方。
- データ品質: 画面読み込みやレビュー/同期操作が継続できず、作業が中断する。

## どう解決すべきか

1. 実装方針。
   - `api-client.ts` に typed API error を導入し、`status`, `error_code`, `error`, `message` を保持する。
   - `isAuthError()` の文字列推測をやめ、typed error + status/code で判定する。
   - `useLoad()` に upload と同じ one-shot reauth guard を入れ、再ログイン後も同じ auth error が続く場合は
     自動遷移せず、画面内 recovery message に止める。
   - `tenant_not_configured`, `session_mismatch`, `permission_denied` はログインループに入れない。
2. UI/UX 方針。
   - 「ログイン情報を更新してください」と「管理者に Cognito/API 設定を確認してください」を分ける。
   - 画面ロード失敗時も CTA は `[ログインして続ける]` と `[再試行]` を原因別に出す。
3. テスト方針。
   - source-level または UI unit test で `useLoad()` の one-shot reauth guard を固定する。
   - `api-client.ts` が `error_code` を保持する contract test を追加する。
   - `/home` or `/sources` 代表画面で 401 after reauth が `/login` loop にならないことを Playwright で確認する。
4. 移行や運用上の注意。
   - stg/live では Cognito issuer/client/JWKS/tenant claim の整合をまず確認する。
   - 一時対応としてブラウザ storage を消しても、API 側設定不一致なら再発する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- API 401 が一律ログインループにならない。
- 再ログインで回復しない auth/config エラーは画面内で止まり、管理者向け原因が分かる。
- `error_code` が web common client で保持される。
- upload で追加した one-shot loop prevention と共通 handler の挙動が矛盾しない。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- Cognito ユーザー管理 UI の追加。
- tenant claim がないユーザーを暗黙に `demo` tenant へ入れること。
- API 側 fail-closed 認証境界の緩和。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx`
- `apps/web/lib/api-client.ts`
- `apps/web/app/api/upload/presign/route.ts`
- `issues/0074-cognito-upload-session-invalid.md`
