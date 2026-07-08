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
- **Fargate 縮小**: web/API/answer 1vCPU→0.25・worker 0.5→0.25。
- **Langfuse 停止**（Fargate＋内部ALB を作らない。観測性は後で `minimalSpec=false` で復帰）。
- NAT/公開ALB はそのまま、answer-service は内部ALBではなく Cloud Map 経由（接続リスク最小＝バランス型）。

概算（東京・常時起動、参考値）: フル `sales` ≈ **$440/月** → `minimalSpec` ≈ **$150〜180/月**。
`cdk synth` 実数: `stage=sales` = Aurora 1 / ECS 3 / ALB 1 / Langfuse無、`stage=prod` = Aurora 2 / ECS 4 / ALB 2 / Langfuse有。

```bash
# 最小・営業/初期本番（使い捨て可）:
npx cdk deploy --context stage=sales
# 耐久性は本番、サイズは最小（RETAIN＋削除保護のまま最安）:
npx cdk deploy --context stage=prod --context minimalSpec=true
# フル本番(HA・Langfuse有):
npx cdk deploy --context stage=prod
```

## ADR-018 構造化取り込み（`structuredIngest` / `ingestVision`）— 既定 OFF

`--context structuredIngest=true` で Docling-first 品質ゲート取り込み（ADR-018）を有効化:

- worker / answer-service に `RAKU_STRUCTURED_INGEST=1` を注入（コネクタ同期・アップロード取り込みの両経路）。
- 両イメージを `INSTALL_DOCLING=1` でビルド（Docling torch-CPU ＋ layout/TableFormer モデルを
  `/opt/docling-models` に焼き込み。ランタイムのモデルDLなし。イメージ約+2GB・ビルド時間増）。
- 両タスクを 1vCPU/4GB に増強（minimalSpec の 0.25vCPU/512MB では torch 推論が載らないため。
  概算 +$60〜70/月）。

さらに `--context ingestVision=bedrock` を足すと、難ページ（図面/手書き/印鑑/低信頼）を Bedrock
Claude vision で処理: VLM draft は常に `draft_visual`（/reviews で人手承認するまで通常回答に不使用）、
手書き/印鑑検出は review 送りを増やす方向にのみ作用。`RAKU_ALLOW_CLOUD_EGRESS=1`（§19 の環境
バックストップ）を注入するが、本番構造化経路は呼び出し直前にテナント provider policy でもゲートする。
`ingestVision` は `structuredIngest=true` と併用（構造化パイプライン内の seam のため単独では無意味）。

```
[ユーザ/Vercel web] → ALB+WAF → ECS:NestJS API ──(ANSWER_SERVICE_URL, Cloud Map)──→ ECS:answer-service(Python)
                                      │  Cognito / Secrets(JWT+内部認証) / Bedrock IAM        └─ Aurora pgvector(RLS)
                                      └─ SQS+DLQ → ECS:ingest worker → S3(KMS)
```

直近の補完（本番が「回答を返す」ために必須だった結線）：
- **answer-service を ECS サービスとして追加**（Cloud Map:8088、container `/healthz`）＋ API に `ANSWER_SERVICE_URL` を注入。
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
# 出力: ApiLoadBalancerDnsName / AnswerServiceInternalUrl / CognitoUserPoolId ...
```

## デプロイ後の一回タスク（スキーマ＋シード）— ワンコマンド化済み
Aurora は空なので **マイグレーション適用＋デモKBシード**が必須。Aurora は隔離サブネット、answer-service は
内部のみ＝**VPC内実行が必要**。これを `MigrateSeedTask`（専用 ops 像 `infra/ops/Dockerfile`：psql＋
`scripts/`＋`infra/db/`）として CDK に内蔵し、デプロイ後に **1コマンド**で実行できます：
```bash
AWS_REGION=ap-northeast-1 STACK=RakuRag-sales bash scripts/aws/migrate-seed.sh
```
スクリプトがスタック出力（cluster / task-def / private subnets / SG）を読んで ECS RunTask を起動し、
`scripts/pg-migrate.sh up`（冪等）→ `scripts/demo/demo_seed.sh`（18件KB）を流して終了を待ちます。失敗時は
CloudWatch ログを案内。`prod` なら `STACK=RakuRag-prod`。

> 補足：このタスクは**常駐サービスではない**（呼ぶまで課金ゼロ）。answer-service の `/healthz` は浅いので
> 空スキーマでもデプロイは安定 → デプロイ完了後にこのスクリプトを実行、の順で動きます。

## フロント（web）— 2通り
**A. AWS内で完結（推奨・同一オリジン）** `--context frontendHosting=aws-nextjs`
- Next.js web が**公開ALBを所有**し既定ターゲット、**API は同じリスナの `/v1/*`** に同居 → ブラウザは
  **同一オリジン**（CORSも https→http 混在ブロックも無し）。`NEXT_PUBLIC_API_BASE` は web イメージの
  **ビルド時に `/v1`（相対）** を埋め込む（`apps/web/Dockerfile` の build-arg）。デモ認証は web に
  `RAKU_ENABLE_DEV_TOKEN_ISSUER=1` ＋ API と同じ署名Secret を注入済み（発行トークンがAPIで検証可）。
- **TLS/ドメイン**: `--context domainName=demo.example.com` を付けると **ACM(DNS検証)証明書＋HTTPS:443＋
  80→443リダイレクト**を自動作成。デプロイ中にACMのDNS検証レコードを足し、`demo.example.com` を ALB の
  DNS 名へ向ける（Route53 Alias か任意DNSのCNAME）。付けない場合は HTTP:80（同一オリジンのまま、TLSは後付け可）。

```bash
# AWS完結・TLS付き（最小スペック）:
npx cdk deploy --context stage=sales --context frontendHosting=aws-nextjs --context domainName=demo.example.com

# Cognitoログイン + Basic認証つき:
npx cdk deploy \
  --context stage=sales \
  --context frontendHosting=aws-nextjs \
  --context authMode=cognito \
  --context basicAuthUser=raku
```
`cdk synth` 実数(aws-nextjs)：公開ALB=1 / リスナ既定=web・Rule `/v1/*`=API / domain時はACM1＋443＋80リダイレクト。

### Cognito ログイン

`authMode=cognito` では、web の `/login` が通常のメールアドレス/パスワード画面として動作し、
Cognito User Pool の `USER_PASSWORD_AUTH` で取得した JWT を API の Bearer token として送ります。
API は JWKS で署名検証し、`custom:tenant_id` と `cognito:groups` から tenant/user/roles を確定します。
Hosted UI の callback に依存しないため、営業用の HTTP-only ALB URL でもログイン確認できます。
独自ドメイン/TLSは営業先に見せるURLを整えるタイミングで追加できます。

デプロイ後、ユーザーは Cognito に作成します。例:

```bash
POOL_ID=$(aws cloudformation describe-stacks --stack-name RakuRag-sales \
  --query "Stacks[0].Outputs[?OutputKey=='CognitoUserPoolId'].OutputValue" --output text)

aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username misaki@example.com \
  --user-attributes Name=email,Value=misaki@example.com Name=email_verified,Value=true Name=custom:tenant_id,Value=demo

aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$POOL_ID" \
  --username misaki@example.com \
  --group-name tenant_admin
```

営業デモ用アカウントは、再実行可能な同期スクリプトで作成・補正できます。API は
`custom:tenant_id` を必須の signed claim として検証するため、この属性が欠けるとログイン後の API
呼び出しは `invalid Cognito JWT` になります。

```bash
SALES_DEMO_PASSWORD='<配布するパスワード>' \
  bash scripts/aws/ensure-sales-demo-user.sh
```

### Basic 認証

`basicAuthUser=<user>` を渡すと `${stage}/web-basic-auth` という Secrets Manager シークレットが作られ、
web タスクに `RAKU_BASIC_AUTH_PASSWORD` として注入されます。パスワード取得:

```bash
SECRET=$(aws cloudformation describe-stacks --stack-name RakuRag-sales \
  --query "Stacks[0].Outputs[?OutputKey=='WebBasicAuthSecretName'].OutputValue" --output text)
aws secretsmanager get-secret-value --secret-id "$SECRET" \
  --query SecretString --output text
```

**B. Vercel/外部(external-vercel・既定)** Vercel 側で `NEXT_PUBLIC_API_BASE=https://<ApiLoadBalancerDnsName>/v1`
を設定（このとき API ALB 側に別途 TLS/ドメイン/CORS が必要）。

> 注意（実機未検証）：web/API/同一ALB結線・SG(ALB→API:3000)・ACM は `cdk synth` 緑まで。初回デプロイで
> web "/" と API "/healthz" のヘルスチェック通過・`/v1/*`到達・ブラウザのトークン発行→API検証を実機確認のこと。
> web のサーバ側(SSR)から API を呼ぶ箇所がある場合、相対 `/v1` は解決しない（クライアント側fetch前提）。

## Google Drive コネクタ OAuth（021-gdrive）— デプロイ後の手動設定

スタックは `${stage}/oauth/google` という **プレースホルダの** Secrets Manager シークレット
（出力 `GoogleOAuthConfigSecretName`）を作成します。実値はあなたが投入します（Claude/CDK では作成不可）。

1. **Google Cloud で OAuth クライアント作成**：GCP コンソール → 対象プロジェクトで **Google Drive API** を有効化
   → 「OAuth 同意画面」を構成（スコープ `https://www.googleapis.com/auth/drive.readonly`、テスト中は自分を
   テストユーザに追加）→ **OAuth 2.0 クライアント ID（種別: ウェブアプリ）** を作成。
2. **リダイレクト URI を登録**（`GOOGLE_OAUTH_REDIRECT_URI` と完全一致させる。コールバックは web 側）：
   - ローカル: `http://localhost:3002/oauth/google/callback`
   - デプロイ: `https://<web-origin or ALB ドメイン>/oauth/google/callback`
3. **シークレットに実値を投入**してタスクを再起動：
   ```bash
   SECRET=$(aws cloudformation describe-stacks --stack-name <stack> \
     --query "Stacks[0].Outputs[?OutputKey=='GoogleOAuthConfigSecretName'].OutputValue" --output text)
   aws secretsmanager put-secret-value --secret-id "$SECRET" --secret-string \
     '{"client_id":"...","client_secret":"...","redirect_uri":"https://<web-origin>/oauth/google/callback"}'
   aws ecs update-service --cluster <cluster> --service <stack>-api      --force-new-deployment
   aws ecs update-service --cluster <cluster> --service <stack>-answer   --force-new-deployment
   ```
4. **動作確認**（ライブ）：web で「Google で接続」→ 同意 → 接続済み表示 → データソース保存 → 同期。
   - `client_secret` は **answer-service だけ** が読む（コード/リフレッシュ交換）。API は `client_id`/`redirect_uri`
     （公開値）のみ。リフレッシュトークンは **Secrets Manager（CMK 暗号化）** の `raku/${stage}/<tenant>/gdrive/<conn>`
     に保管され、設定・ログ・ブラウザには出ません。
   - リフレッシュトークン保管は実行時オン（`RAKU_SECRET_STORE=aws`、runtime profile 非依存）。接続記録自体は
     現状インメモリ（answer-service 再起動で要再接続）。Postgres 永続化（migration `0012_data_source_oauth`）は
     **前方互換の置き場**で、本 PR では実行時の真実源にはしていません。
   - 検証できたら `apps/web` の Google Drive の `readiness` を `three_days` → `ready` に上げてください。

## まだ残る穴（正直に）
- **初回 cdk deploy は未実機検証**（この環境にAWS鍵・Docker無し→ `cdk synth` 緑まで）。最初のデプロイで
  Aurora の `raku_rag`→`SET ROLE raku_app` 権限、Cloud Map 到達、ヘルスチェックを実機確認してください。
- **Cognitoユーザーの初期投入は手動**：User Pool / App Client / groups / Hosted UI / JWT検証はCDKとアプリに
  結線済みですが、初回ユーザー作成・仮パスワード配布・グループ付与は運用手順として実施します。
- **マイグレーション自動化**・**TLS(ACM/独自ドメイン)** は別途。

## 検証済み（このリポ環境）
`cdk synth` 緑（answer-service/ANSWER_SERVICE_URL/Bedrock IAM/内部認証/4イメージfromAsset/4 ECSサービス）、
`tsc` 緑、CI deploy-checks で4イメージ(api/web/worker/answer)を build+SBOM+Trivy。
