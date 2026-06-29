# 0037 — ログイン状態を保持できず毎回ログインが必要になる(系統 = UX / auth-session)

> Priority: **P2/Medium** / Status: In Progress / Labels: `ux`, `auth`, `login`

## 背景(なぜ今)

ユーザー確認で、ログイン画面に「ログインを保持する」選択肢がなく、ブラウザを閉じるたびに再ログインが必要になることが分かった。

## どんな課題か

- Cognito の id/access token が `sessionStorage` のみに保存されている。
- ブラウザを閉じるとログイン状態が失われ、営業デモや通常運用で毎回ログインが必要になる。
- 「この端末ではログインを保持したい」と「共有端末では保持したくない」をユーザーが選べない。
- token 期限切れ後に refresh token で復帰する経路がないため、保持チェックがあっても短時間で再ログインが必要になる恐れがある。

## どこで起きたか

- 画面: `/login`
- API: `POST /api/auth/cognito/password`
- コード: `apps/web/app/login/page.tsx`
- コード: `apps/web/lib/session.ts`
- コード: `apps/web/app/api/auth/cognito/password/route.ts`
- 環境: AWS stg / local web
- run id / ingestion id / correlation id: なし
- 再現条件: Cognito ログイン後にブラウザを閉じ、再度保護画面へアクセスする。

## 影響

- 営業デモへの影響: デモ中に再ログインが増え、操作の流れが切れる。
- 本番クライアントへの影響: 日常利用の摩擦が大きく、SaaS としての体験が悪くなる。
- セキュリティ、監査、データ品質、UX への影響: localStorage への永続保存は共有端末でリスクがあるため、ユーザーが明示的に opt-in でき、サインアウト時に必ず消える必要がある。

## どう解決すべきか

1. 実装方針: `/login` に「ログインを保持する」checkbox を追加し、選択時だけ Cognito token を永続保存する。
2. UI/UX 方針: 共有端末ではオフにすべきことを短い補足文で明示する。
3. テスト方針: checkbox あり/なし、初回パスワード変更、refresh token 復帰、サインアウトで永続保存が消えることを確認する。
4. 移行や運用上の注意: server-side auth/tenant/role 判定は変更しない。ブラウザ保存は利便性のみで、セキュリティ境界にしない。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- Cognito ログイン画面で「ログインを保持する」を選択できる。
- 未選択時は従来通り sessionStorage のみで動作する。
- 選択時はブラウザ再起動後も token/refresh token が有効な間は保護画面へ復帰できる。
- サインアウトまたは認証失敗時に永続保存された token が削除される。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- httpOnly cookie ベースの auth proxy への全面移行。
- Cognito Hosted UI のデザイン刷新。
- 認証/認可ルール、tenant claim、role claim の変更。
- refresh token の有効期限ポリシー変更。

## 参照

- `/login`
- `apps/web/lib/session.ts`
- `apps/web/app/login/page.tsx`
- `apps/web/app/api/auth/cognito/password/route.ts`
