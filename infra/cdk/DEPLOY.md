# 本番構成デプロイ (CDK) — 営業用も本番も同じスタック

このCDKは **VPC / Aurora Serverless v2(pgvector) / ECS Fargate(API・answer-service・ingest worker・
Langfuse) / Cognito / S3・SQS・KMS / WAF / CloudWatch** を1スタックで定義します。営業用は同じスタックを
`stage=sales`（非prodなので 1タスク/DESTROY=安価）で、本番は `stage=prod`（2タスク/RETAIN/HA）でデプロイ
します。**構成は完全に同一**、スケールだけ stage で変わります。既定リージョンは **東京(ap-northeast-1)**
（`CDK_DEFAULT_REGION` があればそちら優先）。

## 最小スペック（`minimalSpec`）— 「最低限動く最安」構成
コストの効く部分だけ落とした最小プロファイルを、**耐久性(RETAIN/バックアップ/削除保護)とは独立に**選べます。
`--context minimalSpec=true|false` で上書き（既定: 非prod=ON / prod=OFF）。`minimalSpec` が効かせる差分:

- **Aurora: reader を外し writer 1台のみ**（常時2台→1台 ＝ 最大の削減）／ max ACU 4→2。
- **Fargate 縮小**: API 1vCPU→0.5・worker 0.5→0.25・answer 1vCPU→0.5。
- **Langfuse 停止**（Fargate＋内部ALB を作らない。観測性は後で `minimalSpec=false` で復帰）。
- NAT/ALB はそのまま（接続リスク最小＝バランス型）。

概算（東京・常時起動、参考値）: フル `sales` ≈ **$440/月** → `minimalSpec` ≈ **$150〜180/月**。
`cdk synth` 実数: `stage=sales` = Aurora 1 / ECS 3 / ALB 2 / Langfuse無、`stage=prod` = Aurora 2 / ECS 4 / ALB 3 / Langfuse有。

```bash
# 最小・営業/初期本番（使い捨て可）:
npx cdk deploy --context stage=sales
# 耐久性は本番、サイズは最小（RETAIN＋削除保護のまま最安）:
npx cdk deploy --context stage=prod --context minimalSpec=true
# フル本番(HA・Langfuse有):
npx cdk deploy --context stage=prod
```

```
[ユーザ/Vercel web] → ALB+WAF → ECS:NestJS API ──(ANSWER_SERVICE_URL, 内部ALB)──→ ECS:answer-service(Python)
                                      │  Cognito / Secrets(JWT+内部認証) / Bedrock IAM        └─ Aurora pgvector(RLS)
                                      └─ SQS+DLQ → ECS:ingest worker → S3(KMS)
```

直近の補完（本番が「回答を返す」ために必須だった結線）：
- **answer-service を ECS サービスとして追加**（内部ALB:8088、`/healthz`）＋ API に `ANSWER_SERVICE_URL` を注入。
- **全アプリ画像を実 Dockerfile に結線**（`fromAsset`：api/web/worker/answer。以前は `sleep infinity` の雛形）。
- **内部認証シークレット**を API↔answer-service で共有（B6 の X-Internal-Auth）。
- **Bedrock IAM**（`bedrock:InvokeModel*`）を answer-service / worker に付与（#1 セマンティック用、鍵投入で有効）。
- `POSTGRES_URL` を起動時に `DATABASE_*`（パスワードは Secret）から組み立て。

## 前提（初回のみ）
1. AWS アカウント＋デプロイ用 IAM ロール（CD は GitHub OIDC。`deploy.yml` 参照）。
2. `cdk deploy` 実行マシンに **Docker**（`fromAsset` がデプロイ時に画像をビルドして ECR へ push）。
3. `npm ci`（`infra/cdk/`）。

## デプロイ
```bash
cd infra/cdk
npm ci && npm run build
npx cdk bootstrap                     # 初回のみ
npx cdk deploy --context stage=sales  # 営業用（or prod）
# 出力: ApiLoadBalancerDnsName / AnswerServiceInternalLoadBalancerDnsName / CognitoUserPoolId ...
```

## デプロイ後の一回タスク（スキーマ＋シード）
Aurora は空なので、**マイグレーション適用**が必須（営業用はさらにデモ KB をシード）：
```bash
# answer-service イメージ(= src + scripts + psql)で一回限り run-task、または踏み台から:
#   POSTGRES_URL="postgresql://raku_rag:<pw>@<AuroraEndpoint>:5432/raku_rag" bash scripts/pg-migrate.sh up
# 営業デモ KB をシード（answer-service が稼働後）:
#   ANSWER_SERVICE_URL="http://<AnswerServiceInternalLB>:8088" bash scripts/demo/demo_seed.sh
```
（CDK へのマイグレ自動化＝ECS RunTask カスタムリソースは未。当面は上記ワンオフ。）

## フロント（web）
既定は **Vercel(external-vercel)**。Vercel 側で `NEXT_PUBLIC_API_BASE=https://<ApiLoadBalancerDnsName>/v1`
を設定。AWS内で完結させたい場合は `frontendHosting: "aws-nextjs"` だが現状フォールバックは雛形（要結線）。

## まだ残る穴（正直に）
- **初回 cdk deploy は未実機検証**（この環境にAWS鍵・Docker無し→ `cdk synth` 緑まで）。最初のデプロイで
  Aurora の `raku_rag`→`SET ROLE raku_app` 権限、内部ALB到達、ヘルスチェックを実機確認してください。
- **本番認証(Cognito)はアプリ未統合**：API は今 HMAC `X-User-Token`（dev-token発行）。営業デモはこのままで
  可だが、web を本番ビルド(NODE_ENV=production)にすると dev-token 発行が無効化される点に注意（デモは
  Vercel/web を dev、または dev-token override を入れる）。本番は Cognito/JWKS 統合が別ワーク。
- **マイグレーション自動化**・**TLS(ACM/独自ドメイン)** は別途。

## 検証済み（このリポ環境）
`cdk synth` 緑（answer-service/ANSWER_SERVICE_URL/Bedrock IAM/内部認証/4イメージfromAsset/4 ECSサービス）、
`tsc` 緑、CI deploy-checks で4イメージ(api/web/worker/answer)を build+SBOM+Trivy。
