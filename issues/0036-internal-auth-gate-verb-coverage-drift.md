# 0036 — Internal auth gate verb coverage drift(系統 = security / QA)

> Priority: **P1/High** / Status: Addressed in PR #16 / Labels: `security`, `contract-test`, `ci`

## 背景(なぜ今)

PR #16 を `develop` に merge 可能にするため GitHub Actions を再実行したところ、
run `28347798420` の Tier A/full suite で
`tests.contract.test_internal_auth_gate.InternalAuthGateTest.test_both_verbs_enforce_the_gate`
が失敗した。

## どんな課題か

- contract test が internal HTTP verb を GET/POST の 2 種類だけと仮定していた。
- 現在の `apps/answer-service/server.py` には GET/POST/PUT/DELETE の internal handlers があり、
  gate 呼び出しは 4 箇所に増えている。
- `PUT` handler は auth gate より先に request body を読んでおり、認証失敗時にも不要な
  JSON parsing が走る可能性があった。
- 期待挙動は、すべての internal HTTP verb が body parsing や route dispatch より前に
  shared-secret gate を通ること。

## どこで起きたか

- 画面: GitHub PR #16 checks
- API: answer-service internal HTTP boundary
- コード:
  - `apps/answer-service/server.py`
  - `tests/contract/test_internal_auth_gate.py`
- 環境: GitHub Actions
- run id / ingestion id / correlation id: run `28347798420`, Tier A/full suite job `83974574230`
- 再現条件: `scripts/gate.sh all` または full suite 相当を実行する。

## 影響

- 営業デモへの影響: なし。ただし CI が赤いままだと PR を merge できない。
- 本番クライアントへの影響: internal boundary の認証順序が曖昧だと、将来の handler 追加時に
  auth 前処理が混入しやすくなる。
- セキュリティ、監査、データ品質、UX への影響: shared-secret gate の coverage を正しく固定し、
  body parsing より前に fail closed することを明示できる。

## どう解決すべきか

1. 実装方針: `PUT` handler で `path` 抽出と auth gate を body parsing より前に移す。
2. UI/UX 方針: UI 変更なし。
3. テスト方針: GET/POST/PUT/DELETE それぞれの handler source を検査し、auth gate が
   body parsing / route dispatch より前にあることを contract test で固定する。
4. 移行や運用上の注意: 新しい internal verb を追加する場合は同じ gate ordering を守る。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の応答が 401 gate に寄る設計で確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 課題の根本原因が解消されている。
- regression test が追加または更新されている。
- 本番想定の UX として説明可能である。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- internal auth 方式そのものの変更。
- mTLS / ALB / production network topology の変更。
- security/safety gate の緩和。

## 参照

- PR #16
- GitHub Actions run `28347798420`
- Tier A/full suite job `83974574230`
