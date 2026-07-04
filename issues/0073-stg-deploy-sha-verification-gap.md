# 0073 — STG deploy SHA verification gap(系統 = ops / release)

> Priority: **P1/High** / Status: Open / Labels: `ops`, `release`, `stg`, `github-actions`

## 背景(なぜ今)

2026-07-04 の STG 確認で、`develop` の最新変更が反映済みだと思っていたが、実際の STG
CloudFront bundle は古い commit のままだった。調査すると、手動 deploy workflow は
`develop` 指定で実行されていたものの、起動時点の `headSha` が期待していた最新 commit ではなかった。

## どんな課題か

- ユーザー/運用者は「最新の `develop` を deploy した」と認識しやすい。
- 実際には GitHub Actions の run は起動時点の `github.sha` に固定される。
- その後 `develop` が進んでも、既存 run は新しい commit へ追従しない。
- 現状の workflow summary は公開 URL を出すが、deploy 対象 SHA や期待 SHA との一致を強く表示/検証しない。
- STG の画面や health endpoint から「今どの commit が動いているか」を即確認できない。

## どこで起きたか

- 画面: `https://dgjq9rlehwxl7.cloudfront.net/reviews/documents`
- API: `/api/health`, `/v1/health`
- コード: `.github/workflows/deploy.yml`
- 環境: AWS STG / CloudFront / ECS
- run id / ingestion id / correlation id:
  - 古い commit を deploy した run: GitHub Actions `28709605289`, `headSha=d04144d3829f89abf27c6d3f3cf4a6b2c679e652`
  - 期待 commit を再 deploy した run: GitHub Actions `28710387230`, `headSha=b7fe6fa9e930afe2f46f1edb6deff850b0a035dc`
- 再現条件:
  - `develop` を手動 deploy する。
  - deploy run 起動後、または起動直前の認識差で `develop` が新しい merge commit に進む。
  - STG 確認時に「branch 名」だけを見て、実際の `headSha` を確認しない。

## 影響

- 営業デモへの影響: 新 UI / 新機能が反映されたと思って案内しても、STG では古い bundle が表示される。
- 本番クライアントへの影響: release 確認の信頼性が下がり、修正済み/未修正の判断を誤る。
- セキュリティ、監査、データ品質、UX への影響:
  - deploy された commit の証跡が弱く、監査・切り戻し判断が遅れる。
  - UI 確認と commit の対応関係が曖昧になり、QA の false negative が増える。

## どう解決すべきか

1. 実装方針。
   - `deploy.yml` に `expected_sha` 入力を追加する。
   - `Preflight` で `expected_sha` が指定されている場合、`github.sha` と完全一致しなければ fail する。
   - STG/develop deploy では、必要に応じて `git ls-remote origin develop` の head と `github.sha` も比較し、古い head を deploy しようとした場合に fail する。
   - workflow summary に `stage`, `branch`, `github.sha`, commit subject, deploy run URL, CloudFormation update time を出す。
   - アプリ runtime に `DEPLOY_COMMIT_SHA` を渡し、health/version endpoint または static endpoint から確認できるようにする。
2. UI/UX 方針。
   - STG 管理者向けの診断表示または health/version レスポンスで、現在の deploy SHA を確認できるようにする。
   - 一般ユーザー画面には不要な内部情報を出さない。
3. テスト方針。
   - `expected_sha` と `github.sha` が一致しない場合、workflow が deploy 前に失敗することを shell/unit 相当で確認する。
   - deploy summary に commit 情報が出ることを CI 上で確認する。
   - STG smoke で runtime SHA が期待値と一致することを確認する。
4. 移行や運用上の注意。
   - 当面の運用では、deploy 前に `git rev-parse origin/develop` で SHA を控え、Actions run の `headSha` と一致することを確認する。
   - CloudFront の見た目確認だけで判断せず、run summary と runtime SHA をセットで確認する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- `expected_sha` 指定時、違う commit の deploy が AWS 更新前に失敗する。
- deploy summary から「どの commit をどの環境に出したか」が即分かる。
- STG の health/version 確認で runtime commit SHA が分かる。
- docs/runbook に「branch 名ではなく SHA を確認する」手順が追記されている。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- prod deploy の承認ゲート緩和。
- AWS 権限の拡大。
- security/safety gate の bypass。
- CloudFront キャッシュだけを原因とみなす対症療法。

## 参照

- `.github/workflows/deploy.yml`
- `infra/cdk/DEPLOY-CI.md`
- GitHub Actions run `28709605289`
- GitHub Actions run `28710387230`
- commit `d04144d3829f89abf27c6d3f3cf4a6b2c679e652`
- commit `b7fe6fa9e930afe2f46f1edb6deff850b0a035dc`
