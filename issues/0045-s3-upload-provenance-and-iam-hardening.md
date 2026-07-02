# 0045 — S3 upload provenance を upload_id record と IAM 制約でさらに強化する(系統 = security / ingestion / architecture)

> Priority: **P2 / Medium** / Status: **In Progress(provenance record landed 2026-07-02; IAM 絞り込みが残)** / Labels: `security`, `ingestion`, `s3`, `defense-in-depth`

## 背景(なぜ今)

0044 で file upload の S3 object は `tenants/{tenant_id}/uploads/...` prefix と metadata を持ち、
`/v1/ingest` と `/internal/ingest` の両方で bucket / prefix / metadata / object size を検証するようになった。
これで pre-ingest の tenant ownership gap は解消したが、将来的な control-plane と IAM の強化余地が残る。

## どんな課題か

- 期待挙動: `/v1/ingest` は raw `s3://bucket/key` ではなく、サーバーが発行・記録した `upload_id` を受け取り、DB record から bucket/key/tenant/user/size/metadata を解決する。
- 現状: 0044 対応後も API contract は raw `s3://` ref を受ける。prefix/metadata検証で防御しているが、provenance record はない。
- 期待挙動: IAM も可能な範囲で tenant prefix / upload prefix に寄せ、アプリ検証に加えてクラウド権限でも誤読取のblast radiusを下げる。
- 現状: ECS task role は document bucket に対して広めの read/write を持つ。

## どこで起きたか

- 画面: `/sources/new`
- API: `POST /api/upload/presign`, `POST /v1/ingest`, `POST /internal/ingest`
- コード:
  - `apps/web/app/api/upload/presign/route.ts`
  - `apps/api/src/ingest/ingest.controller.ts`
  - `apps/answer-service/server.py`
  - `infra/cdk/lib/raku-rag-stack.ts`
  - future migration / repository for upload records
- 環境: AWS-hosted Next.js + shared document S3 bucket
- run id / ingestion id / correlation id: なし
- 再現条件: 0044 の根本gapは再現しない。これは追加hardening課題。

## 影響

- 営業デモへの影響: 直接のUI影響はない。
- 本番クライアントへの影響: upload provenance がDBに残ると監査・再試行・失敗調査が明確になる。
- セキュリティ、監査、データ品質、UX への影響: raw ref 依存を減らし、S3 object と取込操作の所有・有効期限・利用済み状態を監査しやすくする。

## どう解決すべきか

1. `upload_records` などの tenant-scoped table を追加し、`upload_id`, `tenant_id`, `user_id`, `bucket`, `key`, `content_length`, `content_type`, `metadata`, `expires_at`, `consumed_at` を保存する。
2. `/api/upload/presign` または API側 endpoint で upload record を作成し、ブラウザには `upload_id` を返す。
3. `/v1/ingest` は `upload_id` を受け、signed tenant と record tenant の一致、期限、未使用状態、S3 `HeadObject` を確認してから内部 ingest へ渡す。
4. 既存 `ref` 互換は移行期間のみ残し、OpenAPIに deprecated path として明記する。
5. CDK/IAM は可能なら web/API/answer/worker task role を用途別に分け、upload prefix への PUT と ingest read を必要最小限へ寄せる。
6. API e2e、migration contract、S3 head-object fake test、OpenAPI contract を追加する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- `/v1/ingest` が `upload_id` から S3 object を解決できる。
- 別 tenant の `upload_id`、期限切れ、利用済み、metadata不一致、size超過は拒否される。
- raw `s3://` ref の扱いが明示的に deprecated もしくは管理者専用に制限されている。
- migration / repository / API / OpenAPI / e2e test がある。
- IAM 変更を行う場合は CDK contract test がある。

## スコープ外

- 顧客ごとの物理 bucket 分離への即時移行。
- 0044 で解消済みの prefix/metadata validation の緩和。
- demo-only bypass。

## 参照

- `issues/0044-s3-upload-tenant-ref-ownership-gap.md`
- `apps/web/app/api/upload/presign/route.ts`
- `apps/api/src/ingest/ingest.controller.ts`
- `apps/answer-service/server.py`
- `src/raku_rag/providers/connectors.py`
- `infra/cdk/lib/raku-rag-stack.ts`

## 対応メモ(2026-07-02 — provenance record 実装)

- migration `0020_upload_records.sql`(RLS-forced, one-time `consumed_at`, `expires_at`)。
- `/api/upload/presign` は presign **前に** `POST /v1/uploads` で record を登録(fail-closed)。
- `/v1/ingest` / `/internal/ingest` は `upload_id` を受け、record から bucket/key を解決。
  未登録/期限切れ/消費済み/record と ref 不一致は failed。成功時に `consumed_at` を原子的に記録
  (再実行は "upload already consumed")。失敗 job は record を残す(リトライ可)。
- strict mode: `RAKU_REQUIRE_UPLOAD_RECORD=1` で生の `s3://` ref(upload_id なし)を拒否。
  全クライアントが upload_id を送るようになってから有効化(runbook §5)。
- テスト: `tests/unit/test_upload_records.py` / `tests/integration/test_ingest_upload_provenance.py`
  / `tests/contract/test_upload_presign_route.py`。実PG(raku_parity)で RLS 分離・原子的一回消費を smoke 済み。
- 残: ECS task role の tenant/upload prefix への IAM 絞り込み(document bucket の他用途との共用状況の調査が先)。
