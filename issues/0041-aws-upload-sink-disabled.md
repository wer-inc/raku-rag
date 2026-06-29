# 0041 — AWS Cognito deploy disables file upload sink (area = production / upload)

> Priority: **P1/High** / Status: In Progress / Labels: `production`, `upload`, `aws-nextjs`, `ux`

## 背景(なぜ今)

2026-06-29 に sales AWS 環境の `/sources/new` で file を選択し、「アップロード取込」
を実行すると「取込メッセージ: upload sink disabled」と表示されることが確認された。

## どんな課題か

- ユーザーが手元のファイルをデータソースとして取り込めない。
- 期待挙動: Cognito ログイン済みユーザーは `/api/upload/presign` で S3 presigned URL を発行し、
  ブラウザから S3 へアップロード後、`/v1/ingest` に `s3://...` ref を渡せる。
- 実際の挙動: `/api/upload/presign` が 403 `upload sink disabled` を返し、fallback の
  `/api/upload` も同じ gate で無効化される。
- CDK の aws-nextjs web task では `RAKU_UPLOAD_BUCKET` / `DOCUMENT_BUCKET` と task role の
  bucket 権限は設定されているが、`RAKU_ENABLE_UPLOAD_SINK` が `basicAuthUser || authMode === "dev"`
  のときだけ `1` になるため、Cognito-only deploy では upload sink が閉じる。
- ただし、単純に `RAKU_ENABLE_UPLOAD_SINK=1` を設定すると local/dev 用の inline fallback
  `/api/upload` も同じ flag で有効になり、現状この route は Cognito session validation を持たない。
  本番修正では presigned S3 upload と inline fallback の gate を分けるか、fallback 側にも認証を入れる必要がある。

## どこで起きたか

- 画面: `/sources/new`
- API: `POST /api/upload/presign`, fallback `POST /api/upload`
- コード:
  - `apps/web/app/api/upload/presign/route.ts`
  - `apps/web/app/api/upload/route.ts`
  - `apps/web/app/components/FullSaasScreen.tsx`
  - `infra/cdk/lib/raku-rag-stack.ts`
- 環境: sales AWS aws-nextjs / Cognito auth / no Basic auth
- run id / ingestion id / correlation id: none; ingest is not reached.
- 再現条件:
  - Public URL: `http://rakura-awsne-r4xgwhvpgcec-1715490950.ap-northeast-1.elb.amazonaws.com`
  - `curl -i -X POST /api/upload/presign` with a valid-looking JSON body returns
    `HTTP/1.1 403 Forbidden` and `{"error":"upload sink disabled"}` before auth validation.

## 影響

- 営業デモ: 手元ファイルのアップロード取込デモが失敗する。
- 本番クライアント: 初期ナレッジ投入や追加文書投入ができない。
- セキュリティ: upload sink を単純に常時開放するとリスクがあるため、Cognito session validation,
  S3 bucket scoping, object key prefix, size limit, content-type handlingを維持する必要がある。
- UX: ユーザーには環境設定エラーがそのまま表示され、何を直せばよいか分からない。

## どう解決すべきか

1. 実装方針。
   - aws-nextjs deploy では `RAKU_UPLOAD_BUCKET` が設定され、`/api/upload/presign` 側に
     Cognito session validation があるため、presigned S3 upload を Cognito-only でも有効化できるようにする。
   - 例: CDK context または workflow input に `enableUploadSink` を追加し、default は
     `aws-nextjs && (authMode === "cognito" || authMode === "dev")` 相当にする。
   - fallback inline `/api/upload` は local/dev 用として扱い、本番では無効のままにするか Cognito 認証を必須にする。
2. UI/UX 方針。
   - 403/501 のまま fallback して同じエラーを二重に出すのではなく、`presign` が disabled の場合は
     「この環境ではファイルアップロードが無効です。管理者にアップロード設定を確認してください。」
     のようなユーザー向け文言に変換する。
3. テスト方針。
   - CDK contract test に Cognito aws-nextjs でも upload sink が有効になることを追加する。
   - `/api/upload/presign` の disabled/enabled/auth failure の単体または route-level テストを追加する。
   - Playwright または API smoke で file upload の happy path を確認する。
4. 移行や運用上の注意。
   - 既存 sales stack へ反映するには CDK deploy が必要。
   - upload 有効化は billed/cloud deploy action なので明示承認後に実施する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- Cognito-only sales deploy で file upload の presign が `upload sink disabled` にならない。
- ログインしていない/無効な session では presign が 401 になる。
- upload object は tenant/user 境界を越えて露出しない。
- `/v1/ingest` まで到達し、アップロード文書が指定した approval status で登録される。
- regression test が追加または更新されている。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- 認証なし upload の許可。
- bucket policy の public read/write 化。
- size limit や session validation の緩和。
- upload 以外の connector 同期仕様変更。

## 参照

- `apps/web/app/api/upload/presign/route.ts`
- `apps/web/app/api/upload/route.ts`
- `apps/web/app/components/FullSaasScreen.tsx`
- `infra/cdk/lib/raku-rag-stack.ts`
- Live reproduction: `POST http://rakura-awsne-r4xgwhvpgcec-1715490950.ap-northeast-1.elb.amazonaws.com/api/upload/presign`
- 2026-06-29 local fix: split `RAKU_ENABLE_UPLOAD_PRESIGN` from the legacy inline
  `RAKU_ENABLE_UPLOAD_SINK`; Cognito/dev enable S3 presign, inline fallback remains dev-only.
  Pending deploy before the live sales URL changes behavior.
