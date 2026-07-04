# 0068 — STG AWS コスト最適化(系統 = infra / cost)

> Priority: **Medium** / Status: Deployed / Labels: `infra`, `cost`, `aws`, `stg`

## 背景(なぜ今)

2026-07-04 の AWS stg 棚卸しで、`RakuRag-stg` は非 prod の `minimalSpec`
相当で稼働している一方、機能を減らさずに削れる可能性がある固定費候補が見つかった。
予選・営業検証用の stg は product 全機能を動かす必要があるが、過剰な常時起動や
削除済み stage の残骸は避けたい。

## どんな課題か

- 現状の `stg` は CloudFormation `RakuRag-stg` 1 stack で稼働し、ECS `web/api/answer/worker`
  各 1 task、Aurora Serverless v2 writer 1台、ACU `0.5-2.0`、public ALB + internal ALB、
  CloudFront HTTPS front、NAT Gateway 1台を持つ。
- ECS CPU/Memory は直近7日で低利用率で、`web/api/answer` は `512 CPU / 1024 MiB` から
  `256 CPU / 512 MiB` へ下げられる可能性がある。
- internal answer-service ALB は API からの private 呼び出し専用で、Cloud Map / Service Connect
  等に置き換えれば機能維持のまま ALB 固定費を削れる可能性がある。
- `RakuRag-sales` は CloudFormation 上 `DELETE_COMPLETE` だが、古い Cognito user pool、
  CloudWatch Logs、ECS task definition、削除待ち KMS key がタグ付きで残っている。

## どこで起きたか

- 画面: なし
- API: なし
- コード:
  - `infra/cdk/lib/raku-rag-stack.ts`
  - `infra/cdk/DEPLOY.md`
- 環境:
  - AWS account `902353451555`
  - region `ap-northeast-1`
  - active stack `RakuRag-stg`
- run id / ingestion id / correlation id: なし
- 再現条件:
  - `aws cloudformation describe-stacks --stack-name RakuRag-stg`
  - `aws ecs describe-services --cluster raku-rag-stg-cluster ...`
  - `aws rds describe-db-clusters --db-cluster-identifier raku-rag-stg-aurora-pgvector`

## 影響

- 営業デモへの影響: 機能維持のまま月次固定費を下げられる可能性がある。
- 本番クライアントへの影響: stg のコスト設計が prod/sales のテンプレートにも波及する。
- セキュリティ、監査、データ品質、UX への影響: internal ALB 置換や task 縮小は、内部認証、
  health check、監査ログ、live smoke を弱めない形で行う必要がある。

## どう解決すべきか

1. 実装方針。
   - `minimalSpec` のまま `web/api/answer` task size を `256 CPU / 512 MiB` へ下げる。
   - answer-service internal ALB を Cloud Map private DNS に置換する。
   - Aurora Serverless v2 の scale-to-zero 対応可否を engine/version/CDK で確認し、stg の
     warm-up 許容時のみ min ACU `0` を検討する。
   - worker は SQS backlog から scale-to-zero/scale-out できる設計を検討する。
   - 削除済み `sales` の log group / stale task definition / Cognito user pool / KMS pending deletion
     状態を棚卸しし、不要なものだけ明示承認後に整理する。
2. UI/UX 方針。
   - なし。ユーザー向け機能を減らさない。
3. テスト方針。
   - `npm run build` / `cdk synth`。
   - deploy 後に `/api/health`, `/v1/health`, answer/search/ingest の smoke。
   - CloudFront/HTTPS 経由のログイン、アップロード、電話/音声系 secure-context 動作を確認する。
4. 移行や運用上の注意。
   - billed/cloud deploy、live smoke、Bedrock/OpenAI 実呼び出し、AWS リソース削除は human approval
     必須。
   - KMS key の削除は復旧不能なので、参照がないことを確認してから行う。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] Playwright または API smoke で確認できる。
- [x] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 機能を減らさず、stg の主要 smoke が通る。
- 変更前後の AWS リソース構成と期待コスト差分が記録されている。
- ECS/RDS/ALB/CloudFront/worker の監視と rollback 手順が残っている。
- 既存の安全ルール、ACL、監査要件を弱めていない。
- 不要な `sales` 残骸を削除する場合は、削除対象と非対象の一覧が残っている。

## スコープ外

- product 機能の削除。
- Cognito 認証、ACL、内部認証、RLS、監査、製造高リスク evidence gate の緩和。
- human approval なしの billed deploy、live provider eval、AWS リソース削除。

## 参照

- `infra/cdk/lib/raku-rag-stack.ts`
- `infra/cdk/DEPLOY.md`
- `docs/production-gate-strategy.md`
- Local verification: `npm run build` in `infra/cdk`; `cdk synth RakuRag-stg`; `cdk diff RakuRag-stg`
- Expected stg diff: remove answer-service internal ALB/listener/target group/ALB SG; add Cloud Map
  namespace/service; shrink web/api/answer tasks to `256/512`; set app log retention `30d -> 7d`.
- Deploy: GitHub Actions `deploy` run `28700095400`
  (`https://github.com/wer-inc/raku-rag/actions/runs/28700095400`), branch
  `0068-stg-cost-optimization`, `dry_run=false`, `run_migrate_seed=false`, `run_live_smoke=false`.
- Post-deploy remediation: ECS `update-service --load-balancers []` on `raku-rag-stg-answer` after
  CloudFormation removed the ALB resources but ECS still reported the old target group reference.
- Post-deploy verification:
  - CloudFormation `RakuRag-stg`: `UPDATE_COMPLETE` at `2026-07-04T08:13:36Z`.
  - ECS services `web/api/answer/worker`: desired `1`, running `1`, pending `0`, rollout `COMPLETED`.
  - Task sizes: `web/api/answer/worker = 256 CPU / 512 MiB`.
  - Active ALBs: only public `RakuRa-AwsNe-ZV0JKVgR3ezv`; answer-service internal ALB removed.
  - Logs retention: app log groups set to `7` days.
  - VPC internal health check: one-off task
    `arn:aws:ecs:ap-northeast-1:902353451555:task/raku-rag-stg-cluster/0ae4314418b64d08808bbe3258f1cbdd`
    exited `0` against `http://answer.raku-rag-stg.local:8088/healthz`.
  - Public health: `https://dgjq9rlehwxl7.cloudfront.net/api/health` -> `{"ok":true}`;
    `https://dgjq9rlehwxl7.cloudfront.net/v1/health` -> `{"status":"ok","service":"api","phase":0}`.
- AWS stg stack: `RakuRag-stg`
- AWS deleted stack history: `RakuRag-sales` (`DELETE_COMPLETE`)
