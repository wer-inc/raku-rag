# 営業用 単一VM デプロイ (AWS)

プロスペクト向けデモ環境を **EC2 1台** に、検証済みの `scripts/demo/demo_up.sh` と同じスタック
（Postgres+pgvector / Python answer-service / NestJS API / Next.js web）で立ち上げます。nginx 経由で
`http://<public-ip>/` から触れます。本番(CDK: Aurora/ECS/Cognito)に進む前の、最速・最安の営業環境。

```
ブラウザ → nginx:80 ┬─ /v1/ → NestJS API :3000 ──→ Python answer-service :8088 ─┐
                    └─ /    → Next.js web :3002 (dev, dev-token発行)             │
                                                         Postgres+pgvector :5432 ┘ (raku_demo, 18文書)
```

## 前提
- AWS アカウント＋Terraform ≥1.5、既存の EC2 キーペア。
- リポジトリが clone 可能（public なら不要、private なら read-only PAT を `github_token` に）。
- 認証はデモ用の **dev-token 発行（HMAC）**。本番 Cognito ではないので、**Security Group で接続元を絞る**（`allow_http_cidrs` / `allow_ssh_cidr`）。

## デプロイ（Terraform）
```bash
cd deploy/sales-vm/terraform
terraform init
terraform apply \
  -var 'key_name=YOUR_KEYPAIR' \
  -var 'allow_ssh_cidr=YOUR.IP/32' \
  -var 'allow_http_cidrs=["YOUR.OFFICE.IP/32"]'
# → public_url が出力される。3〜5分待って開く（user-data が clone→provision を実行）。
```
private リポなら `-var 'github_token=ghp_xxx'` を追加。別ブランチは `-var 'repo_branch=...'`。

## デプロイ（手動 / 既存VM）
Ubuntu 24.04 のVMに root で：
```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone --branch develop https://github.com/wer-inc/raku-rag.git /opt/raku-rag
sudo PUBLIC_BASE="http://<このVMの公開IP>" bash /opt/raku-rag/deploy/sales-vm/provision.sh
```

## 運用
| 操作 | コマンド |
|---|---|
| 状態 | `systemctl status raku-answer raku-api raku-web` |
| ログ | `journalctl -u raku-answer -u raku-api -u raku-web -f` |
| **クリーン再シード**（デモ前リセット） | `sudo systemctl restart raku-answer && sudo systemctl restart raku-seed` |
| 設定 | `/etc/raku-rag.env`（secrets/ポート/公開URL） |

answer-service は **(再)起動ごとに `--reset-demo-db --seed`** で**キュレート18文書の初期状態に戻る**ので、商談前に再起動するだけでクリーンになります。

## コスト目安（前回試算）
- m6i.large + EBS + EIP ≒ **~$60–90/月**（インフラ）。AIは**オフライン決定論スタック**で **Bedrock費 $0**。
- 営業デモには十分。詳細・削減策は会話のコスト見積を参照。

## セキュリティ注意（デモ前提）
- **本番ではない**：dev-token 発行（誰でもユーザを名乗れる）／単一VM／TLS無し（http）。
- 必ず **SG で接続元IPを制限**。共有リンク的に使うなら CloudFront/ALB+ACM で **HTTPS 化**を別途。
- 機微な顧客文書を入れるなら、この環境ではなく本番(CDK, KMS/RLS/Cognito)へ。

## 本物品質（任意）：Bedrock を効かせる
既定は hashing 埋め込み＋抽出生成（鍵不要）。セマンティック品質にするには：
1. EC2 のインスタンスロールに `bedrock:InvokeModel`（対象モデルARN）を付与。
2. `/etc/raku-rag.env` に `RAKU_RUNTIME_PROFILE=production` ＋ 埋め込み/モデル設定（`RAKU_EMBEDDING_PROVIDER=bedrock_cohere_multilingual_v3` 等）。
3. `sudo systemctl restart raku-answer raku-api && systemctl restart raku-seed`。
4. 品質は `bash scripts/demo/quality_scorecard.sh`（API_BASE/WEB_BASE を公開URLに）で測定。

## 限界（正直に）
- これは**営業デモ用**。マルチテナント本番・HA・自動スケール・監査保持は **CDK 本番スタック**側。
- web は dev モード（dev-token 発行を有効化するため）。同時アクセスは数名想定。
- 初回 EC2 ブートの実機検証は未（このリポ環境ではデプロイ不可のため）。`journalctl`/`/var/log/raku-provision.log` で確認してください。
