# Quickstart & Validation Guide: Generic RAG Platform

**Feature**: `001-rag-platform` | **Date**: 2026-06-18

本ガイドは MVP の end-to-end 検証シナリオを示す。実装詳細・コードは含まず、`tasks.md` と実装
フェーズに委ねる。詳細は [data-model.md](./data-model.md) / [contracts/](./contracts/) を参照。

## Prerequisites

- Node.js / npm, Python 3.12, Docker（PostgreSQL+pgvector / MinIO(S3互換) / LocalStack SQS / optional Langfuse を testcontainers or compose で起動）
- LLM/Embedding/Rerank provider 資格情報（AWS MVP は Amazon Bedrock Claude / Cohere Embed / Cohere Rerank を既定候補。tenant ProviderPolicy により direct provider や外部 parser provider は opt-in）
- [CR] 画像RAG検証時: OCR provider・（任意）captioning provider・VLM provider（vision対応）の
  資格情報、サンプルのスキャンPDF/画像（EXIF付き・PII含む画像を含める）
- 環境変数: `DATABASE_URL`, `S3_ENDPOINT`/`S3_KEY`/`S3_SECRET`, `SQS_QUEUE_URL`,
  `AWS_REGION`, `BEDROCK_REGION`, `TOKEN_SIGNING_PUBLIC_KEY`

## Setup（概念手順）

1. インフラ起動（PostgreSQL+pgvector / MinIO / LocalStack SQS / optional Langfuse）。
2. DBマイグレーション適用（API と worker が共有する schema migration）。
3. API（NestJS）と Python ingest/evaluation worker（SQS consumer）を起動。
4. tenant・collection・API key・ACLGrant を seed。

## Validation Scenarios（受け入れ基準に対応）

### S1. 取り込み → 検索 → 引用付き回答（US1+US2 / MVP成立点）
1. PDF/Markdown/HTML/text と **日本語文書** を `POST /v1/ingest`。`job_id` を取得。
2. `GET /v1/admin/jobs` で `succeeded` を確認、チャンク生成・index 登録を確認。
3. 文書に答えのある質問を `POST /v1/answer`。
   - **期待**: `status:"ok"`、`citations` に document_id/chunk_id/text_range、`used_chunks` 付き。
   - 日本語の引用範囲が原文上で正しく対応する（offset mapping; FR-003b）。

### S2. 根拠不足（推測しない / SC-002）
1. どの文書にも答えがない質問を `POST /v1/answer`。
   - **期待**: `status:"insufficient_evidence"`、`used_chunks: []`、断定回答なし。

### S3. ACL 漏洩ゼロ（最重要 / SC-004, hard gate）
1. 制限文書を tenant に登録、権限の無い principal の `X-User-Token` で `search`/`answer`。
   - **期待**: 結果・回答・引用・used_chunks のいずれにも制限文書が出ない。LLM context にも不出。

### S4. 削除の即時反映（SC-003, hard gate）
1. 取り込み済み文書を `DELETE /v1/admin/documents/{id}`。
2. 即時に `search`/`answer` を実行。
   - **期待**: tombstone 即時除外で再出現0件。物理削除完了後・キャッシュからも再出現しない。

### S5. テナント分離（FR-021a）
1. tenant A のトークンで tenant B の collection を検索しようとする。
   - **期待**: クロステナント検索が拒否される。

### S6. 差分同期・鮮度（FR-005）
1. ソース側で文書を更新 → 差分同期（スケジュール/オンデマンド）。
   - **期待**: 変更分のみ再Embedding（checksum 変化時）、旧 version は検索・回答に残らない（SC-007）。
   - レスポンスに `freshness`/`indexed_at`/`document_version` を確認。

### S7. 障害時 fail-closed（FR-030）
1. LLM provider を一時停止 → `answer`。**期待**: `temporarily_unavailable`（推測回答なし）。
2. budget を 0 に → `answer`。**期待**: `budget_exceeded`（ACL/根拠不足判定は弱めない）。

### S8. 評価ゲート（SC-001/006）
1. EvaluationSet 登録（PII/secret scrub 必須）→ `POST /v1/evaluations/runs?baseline=true`。
2. 変更後に再 run。
   - **期待**: 検索/生成/latency/cost は baseline 比で回帰ブロック。security_checks（ACL漏洩・
     削除再出現・テナント分離・権限外チャンク混入）が一つでも fail なら `gate_result:"blocked"`。

### S9. トレース（SC-005）
1. 1件の `answer` リクエストの `correlation_id` で、ingestion〜generation を横断トレース。
   - **期待**: 段階別 span が欠落なく取得（トレース率100%）、ログは redaction 済み。

### S10. 画像・ビジュアルRAG（US6 / CR: 画像RAG）
1. スキャンPDF・図表入り文書・画像を `POST /v1/ingest`（captioning 有効化は `options.captioning:true`）。
2. `GET /v1/admin/jobs` で OCR・region抽出・visual embedding 完了を確認。captioning 有効時は
   `caption_status=succeeded`、無効時は `not_requested` を確認。
3. 画像内テキストに関する質問を `POST /v1/answer`（`modalities:["text","visual"]`）。
   - **期待**: `status:"ok"`、citations に `kind:"visual"` の `asset_id`/`page_number`/`region_id`/
     `bbox`/`crop_uri`、OCR由来 text、`used_modalities`、used_chunks。`GET /v1/assets/{asset_id}?region_id=`
     で該当領域/crop を表示。
4. 図表に関する質問 → 該当 region を引用、無関係領域は引用しない。
5. 画像にもOCRにも根拠が無い質問 → `insufficient_evidence`（推測しない）。
6. **captioning 検証**: caption は検索ヒットに寄与するが、citation の一次根拠にならない。caption が
   曖昧/画像と矛盾するケースで推測回答しない。captioning を無効化しても検索/回答が成立する（optional）。
7. **権限外 visual asset/crop/OCR/caption**（別 principal）→ 結果・回答・visual citation・VLM入力・
   thumbnail preview に出ない（SC-009）。
8. visual asset を含む文書を削除 → 画像/OCR/region/crop/generated caption/visual embedding/
   サムネイル/各cache から即時除外、`GET /v1/assets/{asset_id}` も露出しない（SC-009 hard gate）。
9. VLM provider を停止 → `temporarily_unavailable`（OCR/caption だけで推測しない）。captioning provider
   停止 → ingestion 全体は failed にならず `caption_status=failed`、再実行可。
10. 画像内 PII（顔/署名等）+ **EXIF（GPS等）** → policy に従い領域マスク/EXIF strip、ログ・評価
    データに原画像/未マスク領域/高リスクEXIFが残らない。

## Done（MVP 検証完了条件）

- S1〜S2, S3〜S5（security hard gate）, S7 が全て期待通り。
- S8 で baseline 確立＋security hard gate が機能。S9 でトレース欠落なし。
- [CR] S10 で画像取り込み→visual citation 付き回答、visual の ACL漏洩/削除再出現ゼロ（SC-009）。
