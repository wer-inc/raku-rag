# 0048 — security-scan baseline line drift(系統 = CI / security)

> Priority: **P2/Medium** / Status: **Resolved(2026-07-02)** / Labels: `ci`, `security`, `release-gate`

## 背景(なぜ今)

`develop` へ `66f8763` を push した後の GitHub Actions で、stg deploy は成功した一方、
`security-scan.yml` が失敗した。直近の `develop` push でも同じ失敗が連続しており、
今回の実装固有の secret 混入ではなく `.secrets.baseline` のメタデータ drift と見られる。

## どんな課題か

- `detect-secrets-hook --baseline .secrets.baseline` が baseline file を更新したとして exit 123 になる。
- ログ上の要求は `Please git add .secrets.baseline` で、新しい secret 候補の詳細は表示されていない。
- 期待挙動は、baseline の行番号などのメタデータが CI とローカルで一致し、実 secret の検出だけが gate を赤にすること。

## どこで起きたか

- 画面: GitHub Actions checks
- API: なし
- コード:
  - `.github/workflows/security-scan.yml`
  - `.secrets.baseline`
- 環境: GitHub Actions / `develop` push
- run id / ingestion id / correlation id: security-scan run `28427750624`, job `84234808800`; stg deploy run `28427770304`
- 再現条件: `develop` push 後に `security-scan.yml` を実行する。

## 影響

- 営業デモへの影響: stg deploy と `/v1/health` は成功しており、即時の動作影響は確認していない。
- 本番クライアントへの影響: なし。ただし release checklist 上の secret scan gate が赤になる。
- セキュリティ、監査、データ品質、UX への影響: secret scan の赤が常態化すると、本物の secret 混入検知の信頼性が下がる。

## どう解決すべきか

1. 実装方針: CI と同じ `detect-secrets==1.5.0` で baseline を再生成/更新し、差分が line metadata のみか、新規検出があるかをレビューする。
2. UI/UX 方針: UI 変更なし。
3. テスト方針: `security-scan.yml` と同じ `git ls-files ... | detect-secrets-hook --baseline .secrets.baseline` をローカル/CI で green にする。
4. 移行や運用上の注意: baseline 更新で実 secret を allowlist しない。新規検出がある場合は値を削除または test-only allowlist を明示する。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [x] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 課題の根本原因が解消されている。
- regression test が追加または更新されている。
- 本番想定の UX として説明可能である。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- secret scan workflow の無効化。
- `.secrets.baseline` への安易な実 secret allowlist 追加。
- demo-only flag や security/safety gate の bypass。

## 参照

- GitHub Actions security-scan run `28427750624`
- GitHub Actions stg deploy run `28427770304`
- `.github/workflows/security-scan.yml`

## 対応メモ(2026-07-02 Resolved)

- **根本原因**: `.secrets.baseline` の line_number メタデータがコード変更で drift し、
  `detect-secrets-hook` が「baseline を更新した」として exit 123 → CI 赤が常態化していた。
  加えてリダクションテストの意図的ダミー secret 2件が baseline 未登録だった。
- **対応**(PR #41 系〜 #46 の一連で実施):
  1. baseline を CI と同じ `detect-secrets==1.5.0` で再生成(行番号 drift のみで新規実 secret なしをレビュー確認)。
  2. リダクションテストの fixture は行 drift に強い **inline `pragma: allowlist secret`** 方式へ
     (`tests/unit/test_phone_redaction.py`)。ただし separation 保護対象の
     `tests/security/test_phone_handoff_redaction.py` は不変更とし、baseline 監査エントリで対応。
  3. 運用知見: hook の exit 123 は「更新された baseline を `git add` して再実行」が正; **新規** secret は
     hook では追加されず `detect-secrets scan --baseline` を使う(値レビュー必須)。
- **検証**: security-scan は #44 以降の全 PR(#44〜#52)と develop push で **連続 green**。
  scanner self-test(シード鍵の検知)も green — gate を弱めずに解消。
