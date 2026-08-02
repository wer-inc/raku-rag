# CI デプロイ (GitHub Actions) — Docker不要・鍵を貼らない

GitHub Actions の runner には Docker があるので、**イメージのビルドも `cdk deploy` も CI 上で実行**します。
あなたのPCにもサンドボックスにも **Docker は不要**。AWS 認証は **OIDC**（長期アクセスキーを作らない/貼らない）。

```
[手動実行 or 後でpush] → GitHub Actions(Docker有) → OIDCでAWSにrole assume
   → cdk bootstrap → cdk deploy(5イメージbuild&push&スタック構築) → migrate-seed(スキーマ+デモKB)
```

## 一回だけの準備（AWS側 + GitHub側）

### 1. OIDCプロバイダ + デプロイロールを作成（AWSコンソール）
`infra/cdk/github-oidc.cfn.yaml` を CloudFormation で1スタック作成するだけ：

- コンソール: **CloudFormation → スタックの作成 → テンプレートをアップロード** → `infra/cdk/github-oidc.cfn.yaml` →
  パラメータ既定（`GitHubOrg=wer-inc` / `GitHubRepo=raku-rag`）→ **「IAMリソース作成を許可」にチェック** → 作成
- またはCLI:
  ```bash
  aws cloudformation deploy --template-file infra/cdk/github-oidc.cfn.yaml \
    --stack-name raku-rag-github-oidc --capabilities CAPABILITY_NAMED_IAM
  ```
- 出力 **`RoleArn`**（`arn:aws:iam::<account>:role/raku-rag-github-deploy`）を控える。
- 既にこのアカウントに GitHub OIDC プロバイダがある場合はパラメータ `CreateOidcProvider=false`。

> **権限（既定で最小権限）**: パラメータ `PermissionsMode` の既定は **`cdk-scoped`** = このロールは
> 「CDKのbootstrapロールをassume」＋「migrate-seedタスク実行」しかできません（アカウント全権は持たない。
> 実際のデプロイ権限は CloudFormation 実行ロール側＝CloudFormationだけがassume可能）。万一スコープ不足で
> デプロイが失敗したら、一時的に `PermissionsMode=admin`（AdministratorAccess）にして通し、後で戻せます。
> **信頼範囲**: `GitHubSubjectFilters` 既定は
> **`repo:wer-inc/raku-rag:environment:sales,repo:wer-inc/raku-rag:environment:stg`** です。
> deploy workflow は GitHub Environment を使うため OIDC の `sub` も environment 形式になります。
> `*`=全ブランチ/全環境は危険なので使わないでください。ワークフローは必ず **develop** ブランチで実行してください。

### 2. 一回だけ：CDK bootstrap（AWS CloudShell・Docker不要）
`cdk-scoped` ロールは bootstrap できない設計なので、bootstrap は管理者セッションで一度だけ行います。
**AWSコンソール右上の CloudShell**（Docker不要・Node同梱）で：
```bash
npx aws-cdk@2 bootstrap aws://<ACCOUNT_ID>/ap-northeast-1
```
（bootstrap はイメージをビルドしないので CloudShell で実行できます。1アカウント×リージョンに一度だけ。）

### 3. GitHub にリポジトリ変数を登録
**GitHub → リポジトリ → Settings → Secrets and variables → Actions → Variables（Secretsではない）** で：
- `AWS_DEPLOY_ROLE_ARN` = 上の RoleArn
- `AWS_REGION` = `ap-northeast-1`（未設定なら既定で東京）

### 4.（任意）prod に承認ゲート
**Settings → Environments → `prod`** を作り、Required reviewers を設定すると prod デプロイに承認が要る。

## デプロイの実行
**GitHub → Actions →「deploy」→ Run workflow** で入力を選ぶだけ。

STG などで「最新の `develop` を出したつもりだが、実際は古い commit だった」を防ぐため、
deploy 前に対象 SHA を控えて `expected_sha` に入れる。workflow は AWS 更新前の Preflight で
`github.sha` と `expected_sha` を比較し、不一致なら失敗する。さらに `develop` からの deploy では
`origin/develop` の現在 head とも比較し、run 起動後に `develop` が進んでいた場合も失敗する。

```bash
git fetch origin develop
git rev-parse origin/develop
```

表示された 40 文字 SHA を `expected_sha` に入れてから実行する。完了後は workflow Summary の
`Deploy identity` / `Deploy outputs` で `github.sha` と `Deploy commit` が同じ SHA になっていることを確認する。

| 入力 | 初回おすすめ |
|---|---|
| stage | `sales`（安価・使い捨て可） |
| frontend | `aws-nextjs`（web+API同一オリジン） |
| domain_name | 空（まずHTTPで疎通／後でドメイン追加） |
| run_migrate_seed | ✅（スキーマ適用。デモKB投入は `seed_demo_kb` で制御） |
| seed_demo_kb | `auto`（sales/stg は投入・prod は投入しない。issue 0089。`off` でスキーマのみ） |
| run_live_smoke | 初回はOFF。Environment secrets/vars を入れた後にON |
| structured_ingest | `off`（既定＝従来パイプライン）。`docling` で ADR-018 の Docling-first 品質ゲート取り込みを有効化（worker/answer イメージに Docling+モデルを焼き込み、両タスクを 1vCPU/4GB に増強 ≒ +$60〜70/月・ビルド時間も増）。`docling+bedrock-vision` は難ページの VLM draft（`draft_visual`・HITL承認必須）＋手書き/印鑑検出も Bedrock Claude vision で有効化（`RAKU_ALLOW_CLOUD_EGRESS=1`、テナント provider policy でさらにゲート） |
| expected_sha | deploy したい 40 文字 commit SHA（特に `stg` / `develop` は指定推奨） |
| **dry_run** | **まず `true`**（synthのみ・無変更で配線確認）→ OKなら `false` で本番実行 |

### stg の既知良好プロファイル（Preflight guard で強制）

stg の能力は context 駆動で、**入力を省略するとその能力ごと削除される**（CloudFront・構造化取り込み
+タスク増強・Connect アダプタ・ガードレール）。事故防止のため、`stage=stg` では Preflight が以下との
一致を検査し、外れていれば deploy 前に失敗する（意図的なダウングレードは `allow_stg_downgrade=true`）。

> `auth_mode` もこのガードの対象（2026-07-31 追加）。省略時の既定 `dev` は web タスクに
> `RAKU_ENABLE_DEV_TOKEN_ISSUER=1` を入れ、`apps/web/app/api/dev-token/route.ts` が**リクエストが指定した
> 任意の `tenant_id`** に対して署名トークンを発行する（`user_id=alice`/`misaki` は `tenant_admin` 付き）。
> prod は同ルートの `STAGE_NAME === "prod"` で塞がれるが **stg は塞がれない**ため、公開されている stg で
> 誰でもクロステナントの管理者トークンを作れてしまう。`auth_mode=cognito` は必須。

```bash
gh workflow run deploy.yml \
  -f stage=stg -f frontend=aws-nextjs -f auth_mode=cognito \
  -f embedding_provider=openai -f answer_llm=bedrock \
  -f visual_provider_profile=aws-textract-bedrock \
  -f bedrock_guardrail_id=uv9pc44guprp -f bedrock_guardrail_version=1 \
  -f https_front=cloudfront \
  -f structured_ingest=docling+bedrock-vision \
  -f phone_telephony=connect \
  -f expected_sha=$(git rev-parse origin/develop) \
  -f dry_run=false
```

（`connect_instance_arn` は stg インスタンスが入力の既定値。）

### prod の必須入力（Preflight prod プロファイルガードで強制）

`stage=prod` はワークフローの**入力既定値のままでは通らない**（`auth_mode=dev` / `embedding_provider=hashing`
/ `domain_name` 空はいずれも本番として不正）。Preflight が以下を強制し、バイパス入力は用意していない
（サイズの選択ではなく、有償パイロット運用契約の安全性・品質の不変条件のため）:

| 入力 | prod で必須の値 | 理由 |
|---|---|---|
| `auth_mode` | `cognito` | `dev` は開発用トークン発行経路を有効化する |
| `embedding_provider` | `openai` | hashing 埋め込みは検索品質を静かに落とす（CDK も synth で fail） |
| `domain_name` | 非空 | ALB の ACM による HTTPS |
| `bedrock_guardrail_id` / `_version` | `answer_llm` が `extractive` 以外のとき必須 | 出力ガードレールは Bedrock ApplyGuardrail を**回答テキスト**に適用するのでベンダー非依存（openai/gemini も対象）。prod は常に production プロファイルで動き、ガードレール未設定だと回答経路が fail-closed する |

なお **`stage=prod` は常に `RAKU_RUNTIME_PROFILE=production`** で動きます（issue 0088）。以前は視覚プロバイダか
Bedrock+guardrail が構成されたときだけ profile が付き、`answer_llm=openai|gemini|extractive` ＋ 視覚プロバイダ
default だと prod でも `deterministic` のまま＝出力ガードレール・意味的危険分類・Secrets Manager 秘密ストア等の
production バックストップが**全て無言で無効**でした。現在は prod で構造的に保証されます。

完了後、ワークフローの **Summary に deploy commit と公開URL（`http://<ALB>`）** が出ます。
ブラウザで開いて回答が返ればOK。

### Post-deploy live smoke

`run_live_smoke=true` にすると、deploy 後に Cognito で smoke user の JWT を発行し、
`scripts/prod-smoke.sh` を実行します。Paid pilot promotion では skips なしが条件です。

> **stg では skips=0 に到達できない**（既知の構造的ギャップ）。Langfuse は `deployLangfuse = !minimalSpec`
> で、`minimalSpec` は非prod既定ON・ワークフローからは変更不可のため、stg に Langfuse が存在せず
> `RAKU_SMOKE_LANGFUSE_TRACE_CHECK_URL` のチェックが必ず skip になる。promotion 用の zero-skip 実行には
> 先に `minimal_spec` 入力の追加（または stg での Langfuse 強制）が必要。

GitHub Environment の Secrets:

- `RAKU_SMOKE_USERNAME`
- `RAKU_SMOKE_PASSWORD`
- `RAKU_SMOKE_OTHER_USERNAME` / `RAKU_SMOKE_OTHER_PASSWORD`（cross-tenant probe 用）
- `RAKU_SMOKE_LANGFUSE_TRACE_CHECK_URL`
- `RAKU_SMOKE_DLQ_CHECK_URL`

GitHub Environment の Variables:

- `RAKU_SMOKE_COLLECTION_ID`
- `RAKU_SMOKE_GROUNDED_QUERY`
- `RAKU_SMOKE_HIGH_RISK_QUERY`
- `RAKU_SMOKE_POISON_QUERY`
- `RAKU_SMOKE_ACL_QUERY`
- `RAKU_SMOKE_FORBIDDEN_DOCUMENT_ID`
- `RAKU_SMOKE_DELETED_QUERY`
- `RAKU_SMOKE_DELETED_DOCUMENT_ID`
- `RAKU_PROD_SMOKE_ALLOW_SKIPS`（diagnostics のみ `yes`。promotion では空）

ローカルで同じ smoke を走らせる場合:

```bash
RAKU_PROD_SMOKE_APPROVED=yes \
  RAKU_SMOKE_USERNAME='<redacted>' \
  RAKU_SMOKE_PASSWORD='<redacted>' \
  RAKU_SMOKE_COLLECTION_ID='<collection>' \
  RAKU_SMOKE_GROUNDED_QUERY='<query>' \
  RAKU_SMOKE_HIGH_RISK_QUERY='<query>' \
  RAKU_SMOKE_POISON_QUERY='<query>' \
  STACK=RakuRag-sales \
  AWS_REGION=ap-northeast-1 \
  bash scripts/aws/run-prod-smoke-from-stack.sh
```

## TLS/ドメインを足すとき
`domain_name=demo.example.com` で再実行 → ACM(DNS検証)＋HTTPS＋80→443リダイレクトが入る。デプロイ中に
ACMのDNS検証レコードを足し、`demo.example.com` を ALB の DNS 名へ向ける（Route53 Alias か CNAME）。

## ドメインなしでHTTPSにするとき（ブラウザマイク等）
Web Speech API のマイク（/phone 通話シミュレータ）などブラウザの secure context が必要な機能は
`http://<ALB>` では動かない。ドメインを持っていない場合は **`https_front=cloudfront`** で再実行すると
公開ALBの前に CloudFront が入り、`https://xxx.cloudfront.net` で使える（ドメイン/ACM不要。
`domain_name` とは排他）。URL はスタック出力 **HttpsFrontUrl**（deploy の Summary にも出る）。
Cognito のコールバック/ログアウトURLには CloudFront ドメインが既存URLに追加で自動登録される。
`https_front=cloudfront` のとき、公開ALBの ingress は CloudFront の origin-facing マネージド
プレフィックスリストに限定される（`http://<ALB>` 直アクセスはタイムアウト）。直 ALB での
デバッグが必要なときだけ `--context albPublicIngress=true` で開放できる。

## つまずいたら
各ステップのログ（特に `cdk deploy` / `migrate-seed`）を貼ってください。よくある詰まり: OIDCロールのsub条件
（`repo:wer-inc/raku-rag:*`）不一致、bootstrap未実行（ワークフローが自動実行）、ヘルスチェック猶予。
