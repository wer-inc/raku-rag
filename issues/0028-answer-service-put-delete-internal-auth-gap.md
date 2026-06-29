# 0028 — answer-service PUT/DELETE internal auth gap (security = internal-boundary)

> Priority: **P0** / Status: Fixed in current ChatBot implementation pass / Labels: `security`, `api`, `internal-auth`

## 背景(なぜ今)

ChatBot の `PUT /internal/chat/source-exposure-policies/{policy_id}` を追加するために
`apps/answer-service/server.py` の internal route 実装を確認していたところ、既存の `do_POST` と
`do_GET` は `_internal_auth_ok()` を通る一方で、`do_PUT` と `do_DELETE` は同じ内部認証チェックを
通っていなかった。

## どんな課題か

- `RAKU_INTERNAL_AUTH_SECRET` を設定していても、answer-service の PUT/DELETE internal route が
  shared secret を確認しない。
- 期待挙動: すべての `/internal/*` route は同じ内部境界認証を通る。
- 実際の挙動: `do_PUT` / `do_DELETE` だけがチェック前に処理へ進む。

## どこで起きたか

- 画面: なし
- API: `PUT /internal/*`, `DELETE /internal/*`
- コード: `apps/answer-service/server.py`
- 環境: local/dev/prod answer-service runtime
- run id / ingestion id / correlation id: なし
- 再現条件: `RAKU_INTERNAL_AUTH_SECRET` を設定し、`X-Internal-Auth` なしで answer-service の PUT/DELETE
  internal route を直接呼ぶ。

## 影響

- 営業デモへの影響: answer-service がローカル以外へ露出した構成だと、内部管理操作の説明が弱くなる。
- 本番クライアントへの影響: ネットワーク境界の設定ミス時に internal PUT/DELETE が防御層を失う。
- セキュリティ、監査、データ品質、UX への影響: tenant 管理設定・文書削除・ChatBot 公開設定などの
  mutation 系 internal route の境界防御が不統一になる。

## どう解決すべきか

1. `do_PUT` と `do_DELETE` の先頭で `_internal_auth_ok(path)` を呼び、失敗時は即 return する。
2. UI/UX 方針: ユーザー向け変更なし。
3. テスト方針: answer-service または API e2e で secret 設定時の PUT/DELETE 伝播を追加する。
4. 移行や運用上の注意: `RAKU_INTERNAL_AUTH_SECRET` の設定と API 側 `X-Internal-Auth` 転送を確認する。

## QA checklist

- [ ] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- `do_PUT` / `do_DELETE` が `do_GET` / `do_POST` と同じ internal auth gate を通る。
- regression test が追加または更新されている。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- answer-service の外部公開構成そのものの変更。
- internal auth secret のローテーションや secret store 移行。
- demo-only bypass や auth 無効化。

## 参照

- `apps/answer-service/server.py`
- `apps/api/src/auth/internal-auth.ts`
