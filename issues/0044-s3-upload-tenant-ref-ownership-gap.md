# 0044 — S3 upload の tenant 所有確認が document_ref 境界で不足している(系統 = security / ingestion / tenancy)

> Priority: **P1 / High** / Status: **Resolved(repo-side, not deployed, 2026-06-29)** / Labels: `security`, `ingestion`, `tenancy`, `s3`

## 背景(なぜ今)

ソース追加の file upload で、アップロード済みファイルが S3 に配置されるか、複数テナントでは
どのように制御されるかを確認した。AWS 配置では `/api/upload/presign` が短命の S3 PUT URL を発行し、
`/v1/ingest` が `s3://bucket/key` の `document_ref` を answer-service に渡す。

## どんな課題か

- 期待挙動: S3 object ref は signed principal の tenant に紐づき、別 tenant が同じ ref を取込に使えない。
- 実際の挙動: presign は認証済みセッションを要求するが、object key は `web-uploads/<stage>/<day>/<uuid>` で tenant prefix を含まない。
- answer-service の `S3Connector.fetch(ref)` は `s3://bucket/key` をそのまま `GetObject` し、`document_ref` が呼び出し tenant に属するかを検証していない。
- 取り込み後の document/chunk/ingestion_run は tenant_id + RLS/ACL で分離されるが、取り込み前の S3 ref 所有境界はアプリ側で未固定。

## どこで起きたか

- 画面: `/sources/new`
- API: `POST /api/upload/presign`, `POST /v1/ingest`, `POST /internal/ingest`
- コード:
  - `apps/web/app/api/upload/presign/route.ts`
  - `apps/api/src/ingest/ingest.controller.ts`
  - `apps/answer-service/server.py`
  - `src/raku_rag/providers/connectors.py`
  - `infra/cdk/lib/raku-rag-stack.ts`
- 環境: AWS-hosted Next.js + shared document S3 bucket
- run id / ingestion id / correlation id: なし
- 再現条件: 認証済み tenant が `/v1/ingest` に任意の既知 `s3://bucket/key` を渡した場合の ref 所有確認がない。

## 影響

- 営業デモへの影響: 直接の UI 破綻はないが、マルチテナント説明時に「S3 prefix/metadata で tenant 固定」と言えない。
- 本番クライアントへの影響: S3 ref が漏れた場合、別 tenant の取込パスで再利用されるリスクがある。
- セキュリティ、監査、データ品質、UX への影響: pre-ingest の tenant boundary が DB/RAG 層ほど強くない。取り込み後は RLS/ACL で分離されるが、原本 object の ownership 検証が不足。

## どう解決すべきか

1. 実装方針: presign key を `tenants/{tenant_id}/uploads/{date}/{uuid}` のような tenant prefix に変更し、S3 object metadata/tag に tenant_id を付与する。
2. 実装方針: `/v1/ingest` または `/internal/ingest` で `document_ref` の bucket/prefix/tag が signed tenant と一致しない場合は 403/failed にする。
3. 実装方針: 少なくとも bucket allowlist と prefix validation を gate 化する。task role IAM の追加絞り込みと `upload_id` DB record 化は follow-up issue 0045 に分離する。
4. UI/UX 方針: なし。ユーザーには引き続き `ソース名` とファイル選択だけ見せる。
5. テスト方針: 別 tenant の `s3://` ref を `/v1/ingest` に渡して拒否される e2e/security test を追加する。
6. 移行や運用上の注意: 既存 `web-uploads/<stage>/...` object は移行期間中に legacy allowlist を設けるか、再取込時に tenant prefix へ移す。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] Playwright または API smoke で確認できる。
- [x] AWS stg/live smoke は未実施。ユーザー指示により deploy 不要のため repo-side resolved とする。

## 受け入れ条件(DoD)

- presign された S3 object に tenant ownership が保存されている。
- `/v1/ingest` / `/internal/ingest` は signed tenant と一致しない S3 ref を拒否する。
- S3 bucket/prefix/ref validation の regression test がある。
- 既存の RLS、ACL、承認、監査要件を弱めていない。

## スコープ外

- 顧客ごとの物理 bucket 分離への即時移行。
- raw `s3://...` を廃止して `upload_id` DB record 経由にする制御面の再設計。follow-up: `issues/0045-s3-upload-provenance-and-iam-hardening.md`
- IAM policy の tenant prefix 条件化。follow-up: `issues/0045-s3-upload-provenance-and-iam-hardening.md`
- 既存 RAG retrieval/answer ACL の緩和。
- demo-only bypass。

## 参照

- `apps/web/app/api/upload/presign/route.ts`
- `apps/api/src/ingest/ingest.controller.ts`
- `apps/answer-service/server.py`
- `src/raku_rag/providers/connectors.py`
- `infra/cdk/lib/raku-rag-stack.ts`
- `issues/0045-s3-upload-provenance-and-iam-hardening.md`

## 対応メモ

- 2026-06-29 partial fix:
  - `/api/upload/presign` は `tenants/{tenant_id}/uploads/{date}/{uuid}` prefix に S3 object を配置する。
  - presigned PUT に `x-amz-meta-raku-tenant-id` / `x-amz-meta-raku-user-id` / `x-amz-meta-raku-upload-id` を要求する。
  - `/v1/ingest` は `s3://` ref の bucket allowlist と tenant prefix を検証し、signed tenant と一致しない ref を answer-service へ転送しない。
  - `data:` inline fallback は dev/local 用に維持。
- 2026-06-29 hardening:
  - `/internal/ingest` 側でも `s3://` ref の bucket allowlist / tenant prefix / `HeadObject` metadata / object size を fetch 前に再検証する。
  - S3 object の `raku-tenant-id` / `raku-upload-id` metadata が欠落または不一致の場合は取込失敗にする。
- 2026-06-29 resolved:
  - 0044 の根本課題である pre-ingest S3 ref ownership gap は repo-side で解消済み。
  - 追加の defense-in-depth / control-plane 改善は 0045 に分離した。

## 検証ログ(repo-side)

- `PYTHONPATH=src python3 -m unittest tests.unit.test_connectors tests.integration.test_ingest_mfg_metadata_parse -v`
- `npm run test:e2e --workspace @raku-rag/api -- ingest.e2e-spec.ts`
- `PYTHONPATH=src python3 -m unittest tests.contract.test_openapi -v`
- `python3 -m py_compile apps/answer-service/server.py src/raku_rag/providers/connectors.py`
- `npm run build:shared`
- `npm run typecheck --workspace @raku-rag/api`
- `npm run typecheck --workspace @raku-rag/web`
- `npm run test:api`
- `PYTHONPATH=src python3 -m unittest tests.contract.test_cdk_infrastructure -v`
- `git diff --check`
- `scripts/gate.sh a`
- `scripts/gate.sh separation`
