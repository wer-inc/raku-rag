# 0042 — Production upload ingest fails from Postgres migration drift (area = production / ingestion)

> Priority: **P1/High** / Status: Mitigated / Labels: `production`, `ingestion`, `postgres`, `migration`

## 背景(なぜ今)

2026-06-29 に sales AWS 環境で `/sources/new` のファイルアップロードが
`upload sink disabled` を抜けた後、取込メッセージが `answer-service error: 500` になることを確認した。

## どんな課題か

- ユーザーがファイルを S3 へアップロードできても、RAG への取込が完了しない。
- 期待挙動: presigned upload 後に `/v1/ingest` が answer-service `/internal/ingest` を呼び、
  `ingestion_runs` を `succeeded` または文書単位の `failed` として返す。
- 実際の挙動: answer-service が Postgres `UndefinedColumn` を起こし、API が
  `answer-service error: 500` として 502 を返す。
- 根本原因: 本番 DB の `schema_migrations` が `0013_datasource_sync_runtime` までで止まっているが、
  deployed code は `0014_visual_understanding` の `ingestion_runs.async_provider`,
  `async_job_id`, `async_job_status` を読む。

## どこで起きたか

- 画面: `/sources/new`
- API: `POST /v1/ingest`
- コード:
  - `apps/api/src/ingest/ingest.controller.ts`
  - `apps/answer-service/server.py`
  - `src/raku_rag/production.py`
  - `src/raku_rag/persistence/postgres.py`
  - `infra/db/migrations/postgres/0014_visual_understanding.sql`
- 環境: sales AWS aws-nextjs / Cognito auth / Aurora Postgres
- run id / ingestion id / correlation id:
  - Deploy run: `https://github.com/wer-inc/raku-rag/actions/runs/28370456265`
  - Debug task: `arn:aws:ecs:ap-northeast-1:902353451555:task/raku-rag-sales-cluster/c75560e48a7c4f96a17d363ae15c8146`
  - Debug result object: `s3://raku-rag-sales-902353451555-ap-northeast-1-documents/debug/codex/ingest-direct-20260629T122845Z-8023.json`
  - Migration task: `arn:aws:ecs:ap-northeast-1:902353451555:task/raku-rag-sales-cluster/b89c6b5f6c8f4e22b6f805f895ab2fe8`
  - Post-migration debug task: `arn:aws:ecs:ap-northeast-1:902353451555:task/raku-rag-sales-cluster/f5dfa521a3c84ee889a881afb08b29fb`
  - Post-migration debug result object: `s3://raku-rag-sales-902353451555-ap-northeast-1-documents/debug/codex/ingest-direct-after-migrate-20260629T123351Z-3546.json`
  - Live upload smoke ingestion run: `ing_c1700c8bdfb67b35ed72`
- 再現条件:
  - Live `/api/upload/presign` returns 200 for an authenticated Cognito session.
  - S3 PUT to the presigned URL returns 200.
  - Live `/v1/ingest` returns 502 with `{"message":"answer-service error: 500"}`.
- Mitigation:
  - 2026-06-29: VPC 内 one-off task で `scripts/pg-migrate.sh up` 相当を実行し、
    `0014_visual_understanding` / `0015_visual_provider_policy` を適用済み。
  - Post-migration direct ingest smoke: `run_status=succeeded`, `chunk_count=1`。
  - Live Cognito upload smoke: `login=200`, `presign=200`, `S3 PUT=200`, `/v1/ingest=202`,
    `status=succeeded`, `chunk_count=1`。

## 影響

- 営業デモ: ファイルアップロード取込デモが最後の取込ステップで失敗する。
- 本番クライアント: 新規文書投入ができず、ドキュメント承認キューにも到達しない。
- セキュリティ/監査: tenant/ACL 漏洩ではないが、失敗が generic 500 になり運用調査性が低い。
- UX: ユーザーには `answer-service error: 500` しか見えず、復旧方法が分からない。

## どう解決すべきか

1. 実装方針。
   - sales DB に未適用の `0014_visual_understanding` / `0015_visual_provider_policy` を適用する。
   - deploy workflow の `run_migrate_seed` が確実に実行され、DB schema が deployed code と一致することを
     release smoke で検査する。
   - answer-service の `/internal/ingest` では例外をサーバーログに残す。ただし秘密情報、raw document、
     token、内部 auth header は出さない。
   - API facade は upstream 500 の raw SQL 詳細をユーザーに漏らさず、運用向け correlation id を返せる形にする。
2. UI/UX 方針。
   - ユーザー向けには「取込基盤で一時的なエラーが発生しました。管理者に連絡してください。」などに変換し、
     raw `answer-service error: 500` を直接見せない。
3. テスト方針。
   - Postgres migration status smoke を deploy 後に追加し、required migration が欠けていたら fail する。
   - `/v1/ingest` happy path を Cognito live smoke または production-like smoke に追加する。
   - answer-service ingest 例外時の sanitized logging / API response contract を追加する。
4. 移行や運用上の注意。
   - 既存 sales stack への migration 適用は本番 DB 変更なので明示承認後に実施する。
   - seed の再投入は不要。`scripts/pg-migrate.sh up` のみでよい。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [x] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- sales DB の `schema_migrations` が deployed code の必須 migration まで進んでいる。
- `/sources/new` の file upload が `/v1/ingest` まで成功し、文書が登録される。
- `/internal/ingest` のサーバー例外は sanitized log に残り、ユーザーには raw SQL が漏れない。
- deploy 後 smoke が migration drift を検出できる。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- DB migration をスキップする demo-only fallback。
- raw SQL / secrets / token / document content の UI またはログ露出。
- seed データの再設計。

## 参照

- `infra/db/migrations/postgres/0014_visual_understanding.sql`
- `src/raku_rag/persistence/postgres.py`
- `scripts/pg-migrate.sh`
- `scripts/aws/migrate-seed.sh`
