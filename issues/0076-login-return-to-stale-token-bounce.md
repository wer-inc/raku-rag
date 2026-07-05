# 0076 — return_to ログインが stale token を信じて再ログイン不能になる(系統 = web / cognito-ux)

> Priority: **P0/High** / Status: Fixed / Labels: `web`, `cognito`, `ux`, `stg`

## 背景(なぜ今)

stg CloudFront `https://dgjq9rlehwxl7.cloudfront.net/login?return_to=%2Ffiles` で、
ログイン画面を開いても `/files` に戻され、再ログインできない状態が残っていると報告された。
`0eb3edd` で共通 load handler の one-shot guard は配信済みだったため、配信 JS と実ブラウザ相当の
storage/network を確認した。

## どんな課題か

- 期待: 認証復旧リンクから `/login?return_to=/files` に来た場合は、既存 token が残っていても
  新しいログイン情報を入力できる。
- 実際: login page は `getBrowserSessionState()` がブラウザ内 token をローカル検証で有効と判断すると、
  ログインフォームを表示せず `return_to` へ即遷移した。
- その token を API が `invalid Cognito JWT` として 401 拒否すると、`/files` の独自 loader が
  共通 `useLoad()` を通らず raw error を画面に表示した。

## どこで起きたか

- 画面:
  - `/login?return_to=/files`
  - `/files`
- API:
  - `GET /v1/manufacturing/documents`
  - `GET /v1/manufacturing/drafts`
- コード:
  - `apps/web/app/login/page.tsx`
  - `apps/web/app/components/FullSaasScreen.tsx`
- 環境:
  - stg CloudFront `https://dgjq9rlehwxl7.cloudfront.net`
- run id / ingestion id / correlation id:
  - なし。Playwright 相当の browser storage + network probe。
- 再現条件:
  - ブラウザに issuer/client/tenant/exp のローカル検証は通るが、API 側では拒否される token が残っている。
  - `/login?return_to=/files` にアクセスする。

## 影響

- 営業デモへの影響: ログイン画面に戻ったように見えても再入力できず、ファイル画面へ戻される。
- 本番クライアントへの影響: Cognito/JWKS/client/issuer 設定不一致や古い token 残留時の復旧導線が詰まる。
- セキュリティ/監査: API は fail-closed で正しい。問題は UX と診断情報の扱い。
- データ品質: ファイルアップロードや根拠文書レビュー作業が中断する。

## どう解決すべきか

1. 実装方針。
   - `return_to` 付き login を再認証要求として扱い、既存 browser session を消してフォームを表示する。
   - 自動生成する login URL に `reauth=1` を付けて意図を明示する。
   - `/files` 独自 loader の API 401 も共通 auth recovery に通す。
2. UI/UX 方針。
   - stale token が残っていても、ユーザーは必ず再ログインを試せる。
   - 再ログイン後も API が拒否する場合は自動ループせず、管理者確認メッセージに止める。
3. テスト方針。
   - login page が `return_to`/`reauth=1` で fresh credentials を要求する source-level contract を追加する。
   - `/files` loader が `startLoginRecoveryForAuthError()` と `formatLoadError(...reauthAttempted)` を使うことを固定する。
4. 移行や運用上の注意。
   - stg 反映後、ブラウザ storage に古い token が残るケースで `/login?return_to=/files` を再確認する。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- `/login?return_to=/files` で stale token による即 `/files` bounce が起きない。
- `/files` の初期ロード 401 が raw `invalid Cognito JWT` のみで止まらない。
- 再ログイン後も API が拒否する場合は one-shot で止まり、管理者確認メッセージになる。
- regression test が追加されている。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- Cognito ユーザー管理 UI の追加。
- API 側 JWT/JWKS 認証を緩和すること。
- demo-only fallback tenant の追加。

## 参照

- `apps/web/app/login/page.tsx`
- `apps/web/app/components/FullSaasScreen.tsx`
- `tests/contract/test_web_auth_recovery.py`
- `issues/0075-global-auth-redirect-loop.md`
