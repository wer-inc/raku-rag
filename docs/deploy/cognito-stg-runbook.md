# stg を Cognito 常用に切り替える runbook

目的: stg を `auth_mode=dev`(誰でも `/api/dev-token` でトークン発行可)から `auth_mode=cognito`
に切り替え、「顧客に URL を渡せる」状態にする。コード・CDK は対応済み(切替はデプロイ入力のみ)。

## 1. デプロイ(GitHub Actions)

`deploy.yml` を workflow_dispatch で実行。stg 標準入力との差分は `auth_mode=cognito` だけ:

```
gh workflow run deploy.yml --ref develop \
  -f stage=stg -f frontend=aws-nextjs -f auth_mode=cognito \
  -f embedding_provider=hashing -f answer_llm=extractive \
  -f visual_provider_profile=default -f run_migrate_seed=true -f dry_run=false
```

(実LLM点火と同時にやる場合は `embedding_provider=openai -f answer_llm=bedrock
-f visual_provider_profile=aws-textract-bedrock` に置き換え。この構成は
`runtime_profile=production` になり **Bedrock Guardrail が必須**(無いと全回答が
fail-closed で temporarily_unavailable)。stg 用 Guardrail は作成済み:
`-f bedrock_guardrail_id=uv9pc44guprp -f bedrock_guardrail_version=1` を必ず付ける。)

切替で何が変わるか(CDK `raku-rag-stack.ts`):
- `RAKU_ENABLE_DEV_TOKEN_ISSUER=0` — `/api/dev-token` が閉じる(外形確認の手段が変わる。下記 §3)
- `RAKU_ENABLE_UPLOAD_PRESIGN=1` は維持(cognito でも presign 有効 — issue 0041 の修正)
- `RAKU_ENABLE_UPLOAD_SINK=0` — inline `/api/upload` fallback は dev 専用のまま閉じる

## 2. Cognito ユーザー作成(初回のみ・コンソールまたは CLI)

スタックが作る User Pool(`RakuRag-stg` の出力 `CognitoUserPoolId`)に検証ユーザーを1人作る:

```
aws cognito-idp admin-create-user --user-pool-id <POOL_ID> \
  --username demo-user --user-attributes \
    Name=email,Value=you@example.com \
    Name=custom:tenant_id,Value=demo \
  --temporary-password 'TempPass#2026' --region ap-northeast-1
aws cognito-idp admin-set-user-password --user-pool-id <POOL_ID> \
  --username demo-user --password '<本パスワード>' --permanent --region ap-northeast-1
```

`custom:tenant_id` がテナント割当(未設定は `demo` にフォールバック)。ロールは Cognito groups
(`manageCognitoGroups` context 有効時)または既定ロールで付与。

## 3. 外形確認

1. `/login` → Cognito ログイン(hosted UI または `/api/auth/cognito/password` フロー)
2. `/api/dev-token` が **404/無効** になっていること(dev 発行の遮断確認)
3. チャット/回答: 質問 → 根拠付き回答
4. **アップロード実線(issues 0041/0044/0045/0047 の live 検証)**:
   `/sources/new` または `/files` からファイルを選択 → アップロード取込。
   期待: presign 200 → S3 PUT 200(HeadersNotSigned が出ない)→ ingest 到達。
   S3 コンソールで object key が `tenants/<tenant>/uploads/...` prefix であること、
   metadata に `raku-tenant-id`/`raku-upload-id` が付くことを確認。
5. 同じファイルの ingest を API で再実行 → `upload already consumed` で拒否(one-time 消費)

## 4. ロールバック

同じ dispatch を `auth_mode=dev` で再実行するだけ(スタック更新のみ、データ影響なし)。

## 5. 将来の締め上げ(任意)

- 全 upload クライアントが `upload_id` を送るようになったら answer-service に
  `RAKU_REQUIRE_UPLOAD_RECORD=1` を設定 → 生の `s3://` ref 取込を拒否(0045 strict mode)。
- IAM の tenant-prefix 絞り込みは issue 0045 に残置(document bucket が他用途と共用のため要調査)。
