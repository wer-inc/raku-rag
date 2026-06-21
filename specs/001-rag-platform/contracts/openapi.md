# API Contract: Generic RAG Platform

**Feature**: `001-rag-platform` | **Date**: 2026-06-18 | API First（FR-018/019/020）

すべて `/v1` 配下。認証: tenant/app は API key、エンドユーザー claims は署名付きトークン
（`X-User-Token`）。全レスポンスは追跡識別子と `correlation_id` を含む。OpenAPI(Swagger) を
正本として配布（FR-019a）。

## 共通

- 認証ヘッダ: `Authorization: Bearer <api_key>`（tenant/app/client）, `X-User-Token: <signed>`
  （エンドユーザー claims; search/answer で必須）。
- エラー: `{ "error": { "code", "message", "correlation_id" } }`。redaction 済み。
- Answer/Search status: `ok | insufficient_evidence | budget_exceeded | temporarily_unavailable`。

## Query / Answer

### POST /v1/search
権限・メタデータフィルタ込みのチャンク検索（pre-filter）。
- req: `{ query, collection_id?, filters?, top_k?, score_threshold?, rerank?, query_profile?, retrieval_profile_id?,
  identifier_hints?, modalities?: ["text","visual"] }`
- res 200: `{ status, results: [{ modality:"text"|"visual", source_id, document_id, chunk_id,
  version, retrieval_score, text?, heading_path, freshness,
  asset_id?, page?, bounding_box? /* [CR] visual */ }], correlation_id }`
- 権限外チャンク/visual asset は結果に一切含まない（FR-022/039, SC-004/009）。

### POST /v1/answer
根拠付き回答生成（2段階 groundedness gate）。テキスト・画像の混在を扱う。
- req: `{ query, collection_id?, filters?, query_profile?, retrieval_profile_id?, identifier_hints?, modalities?: ["text","visual"] }`
- res 200 (ok): `{ status:"ok", answer, confidence, used_modalities:["text","visual"],
  citations: [{ kind:"text"|"visual", document_id, source_id, version, retrieval_score,
  chunk_id?, text_range?,                                        // kind=text
  asset_id?, image_id?, page_number?, region_id?, bbox?, crop_uri?, ocr_text? // kind=visual [CR]
  }], used_chunks: [...], freshness, cost, correlation_id }`

**[CR] Visual answer 例（JSON）**:

```json
{
  "status": "ok",
  "answer": "図2の手順では、まずバルブAを閉じてから圧力を確認します。",
  "confidence": 0.82,
  "used_modalities": ["text", "visual"],
  "citations": [
    {
      "kind": "visual",
      "asset_id": "asset_8f3a",
      "image_id": "asset_8f3a",
      "document_id": "doc_123",
      "source_id": "src_manual",
      "version": 3,
      "page_number": 7,
      "region_id": "region_42",
      "bbox": [0.12, 0.34, 0.58, 0.61],
      "crop_uri": "s3://tenant-a/crops/region_42.png",
      "ocr_text": "手順: バルブAを閉じる → 圧力確認",
      "retrieval_score": 0.79
    }
  ],
  "used_chunks": ["region_42", "chunk_991"],
  "freshness": { "indexed_at": "2026-06-18T03:11:00Z", "document_version": 3 },
  "cost": { "vlm_image_tokens": 1420, "ocr": 0, "captioning": 0, "visual_embedding": 0 },
  "correlation_id": "trace_abc"
}
```
> caption は検索補助で citation の一次根拠にしない。bbox は正規化座標 0–1。
- res 200 (insufficient_evidence): `{ status:"insufficient_evidence", used_chunks: [],
  correlation_id }`（推測回答しない; FR-014, SC-002）
- res 200 (budget_exceeded / temporarily_unavailable): 該当 status、回答本文なし。
- **使用チャンク一覧 `used_chunks` を常に返す**（制約）。LLM context は権限確認済みチャンクのみ。

## Ingestion / Admin

### POST /v1/ingest
- req: `{ source_id | upload, collection_id, metadata?, options?: { captioning?: bool } }`
- [CR] 受理フォーマットに 画像（PNG/JPEG/TIFF）・スキャンPDF を含む。画像は OCR・layout/region
  抽出・（option 有効時）captioning・visual embedding を経て index 化（非同期）。EXIF は既定で
  高リスク項目を strip。captioning は collection 既定 or job option で enable/disable（FR-046/047）。
- res 202: `{ job_id?, ingestion_run_id, status_url }`（非同期。AWS MVP は SQS + Python worker が実処理する。Dagster が有効な環境では同じ IngestionRun / DocumentProcessingState を control plane から監視・再実行できる）

### GET /v1/assets/{asset_id}?region_id= [CR: 画像RAG]
visual citation 表示用に、権限確認済みの画像/領域（サムネイル or 切り出し）を返す。
- ACL pre-filter・tenant 分離・tombstone を適用。権限外/削除済みは 404 相当（存在を露出しない）。
- res 200: 画像バイト or `{ asset_id, page, bounding_box, signed_url, expires_at }`。

### GET /v1/admin/jobs?status=&source_id=
互換 job 一覧。新規 ingestion/sync の詳細は `IngestionRun` / `DocumentProcessingState` API を正本にする。
- res 200: `[{ job_id, ingestion_run_id?, type, status, failure_reason?, retry_count, started_at, finished_at, dagster_run_id? }]`

### POST /v1/admin/jobs/{job_id}/retry
失敗ジョブ/文書の再実行（FR-006）。MVP では SQS retry message / IngestionRun retry を作成する。Dagster managed run の場合も同じ `IngestionRun` retry を正本として扱う。

### POST /v1/admin/sources/{source_id}/sync
manual sync request。NestJS API は PostgreSQL に `IngestionRun(status=queued, trigger=manual)` を作成し、AWS MVP では SQS に sync job を enqueue する。Dagster が有効な環境では `ingestion_job sensor` が同じ queued run を観測して実処理または再実行 orchestration を担当できる。
- req: `{ collection_id?, scope?: { source_document_ids? }, force?: bool }`
- res 202: `{ ingestion_run_id, status:"queued", status_url:"/v1/admin/ingestion-runs/{ingestion_run_id}" }`

### GET /v1/admin/sources/{source_id}/sync-status
SourceSyncState と最新 run summary。App admin UI はこの API を表示する。
- res 200: `{ source_id, collection_id, status, cursor?, last_observed_at?, last_successful_sync_at?,
  last_ingestion_run_id?, observed_count, changed_count, deleted_count, skipped_count, failed_count,
  freshness, last_error?, dagster_run_id?, dagster_run_url? }`
- `dagster_run_id` / `dagster_run_url` は内部運用者向け。end user に Dagster UI を直接見せない。

### GET /v1/admin/ingestion-runs/{ingestion_run_id}
IngestionRun の詳細と document processing summary。
- res 200: `{ ingestion_run_id, type, trigger, status, source_id?, collection_id?, started_at?, finished_at?,
  summary:{ observed_count, changed_count, deleted_count, skipped_count, failed_count },
  documents:[{ document_id, source_document_id, parse_status, chunk_status, embedding_status, index_status,
    last_indexed_at?, last_error? }], asset_materializations:[{ dagster_asset_key, partition_key, storage_uri? }],
  dagster_run_id?, dagster_run_url?, correlation_id }`

### GET /v1/admin/documents/{document_id}/processing-status
DocumentProcessingState の詳細。
- res 200: `{ document_id, source_document_id, content_checksum, parser_version, chunking_config_version,
  embedding_model_version, parse_status, chunk_status, embedding_status, index_status, last_indexed_at?,
  last_error?, dagster_run_id? }`

### DELETE /v1/admin/documents/{document_id}
- 即時 tombstone → 非同期カスケード削除（FR-008）。res 202: `{ job_id?, ingestion_run_id }`。

### POST /v1/admin/collections/{id}/reindex
- 再インデックス（並行構築→切替）。res 202: `{ job_id?, ingestion_run_id }`。


### Provider Policy APIs

#### GET /v1/admin/provider-policies
- res 200: `[{ provider_policy_id, tenant_id, collection_id?, name, status, parser_mode, allowed_parser_providers, allowed_llm_providers, allowed_embedding_providers, data_residency_requirement, zero_retention_required, no_train_required, customer_opt_in_status }]`

#### GET /v1/admin/provider-policies/{provider_policy_id}
- res 200: `{ provider_policy_id, parser_mode, allowed_parser_providers, provider_regions, cross_cloud_processing_allowed, zero_retention_required, no_train_required, customer_opt_in_required, customer_opt_in_status, provider_capability_snapshot, fallback_policy, audit_events }`

#### PUT /v1/admin/provider-policies/{provider_policy_id}
- req: `{ parser_mode, allowed_parser_providers, provider_regions, cross_cloud_processing_allowed, zero_retention_required, no_train_required, customer_opt_in_status, fallback_policy, reason }`
- res 200: `{ provider_policy_id, status, provider_config_audit_event_id }`
- Must create ProviderConfigAuditEvent. External parser/OCR providers require customer opt-in where policy requires it.

#### POST /v1/admin/provider-policies/{provider_policy_id}/validate
- req: `{ collection_id?, document_sample_refs?, operation: "parse|embed|rerank|llm|log" }`
- res 200: `{ allowed, reasons[], required_opt_in?, effective_provider, fallback_provider? }`

### Retrieval Profile APIs

#### GET /v1/admin/retrieval-profiles
- res 200: `[{ retrieval_profile_id, name, version, status, metadata_filter_required, identifier_match_enabled, vector_search_enabled, rerank_enabled }]`

#### GET /v1/admin/retrieval-profiles/{retrieval_profile_id}
- res 200: `{ retrieval_profile_id, metadata_filter_required, identifier_fields, keyword_strategy, vector_top_k, vector_score_threshold, rerank_provider, rerank_model, rerank_candidate_limit, final_context_limit, max_context_tokens, minimum_evidence_count, fallback_behavior }`

#### PUT /v1/admin/retrieval-profiles/{retrieval_profile_id}
- req: `{ metadata_filter_required, identifier_match_enabled, identifier_fields, keyword_strategy, vector_top_k, rerank_enabled, rerank_candidate_limit, final_context_limit, max_context_tokens, minimum_evidence_count, reason }`
- res 200: `{ retrieval_profile_id, version, provider_config_audit_event_id }`

#### POST /v1/admin/retrieval-profiles/{retrieval_profile_id}/benchmark
- req: `{ eval_set_id?, industry_id?, sample_size?, compare_to_profile_id? }`
- res 202: `{ evaluation_run_id, status_url }`

### Logging Policy APIs

#### GET /v1/admin/logging-policies/{logging_policy_id}
- res 200: `{ logging_policy_id, raw_user_query_storage, raw_retrieved_context_storage, model_input_storage, model_output_storage, store_citation_ids, store_chunk_ids, store_prompt_template_version, store_model_metadata, store_latency, store_cost, production_sampling_rate, retention_policy_ref }`

#### PUT /v1/admin/logging-policies/{logging_policy_id}
- req: `{ raw_user_query_storage, raw_retrieved_context_storage, model_input_storage, model_output_storage, production_sampling_rate, retention_policy_ref, reason }`
- res 200: `{ logging_policy_id, provider_config_audit_event_id }`
- Default must keep raw retrieved context storage disabled unless explicit opt-in policy exists.

#### GET /v1/admin/provider-config-audit-events
- query: `event_type?`, `correlation_id?`, `collection_id?`
- res 200: `[{ provider_config_audit_event_id, tenant_id, collection_id?, event_type, actor, redacted_before, redacted_after, reason, approval_ref?, created_at, correlation_id? }]`
- Provider/retrieval/logging/model/parser policy changes must be listed tenant-scoped with redacted before/after snapshots.

### Admin 設定 API
- `GET/PUT /v1/admin/datasources/{id}`（同期スケジュール含む）
- `GET/PUT /v1/admin/query-profiles/{id}`（score_threshold/top_k/rerank/llm_model/max_synchronous_llm_calls/max_context_tokens/max_context_chunks 等）
- `GET/PUT /v1/admin/acl`（ACLGrant の付与/取消; deny-by-default）
- `GET/PUT /v1/admin/budgets`（tenant/collection/query budget）

## Evaluation / Feedback

### POST /v1/evaluations/sets
- req: `{ items: [{ question, expected_answer, expected_evidence[] }] }`（PII/secret scrub 必須）

### POST /v1/evaluations/runs
- req: `{ eval_set_id, baseline? }`
- res 202: `{ run_id }`。完了後 metrics（recall@k/citation accuracy/groundedness/p95
  latency/query cost）＋ security_checks（全 pass 必須）。

### GET /v1/evaluations/runs/{run_id}
- res 200: `{ status, metrics, baseline_comparison, security_checks, gate_result }`。
  security_checks のいずれか fail → `gate_result:"blocked"`（absolute hard gate）。


### POST /v1/evaluations/poc-runs
Create the two-stage PoC benchmark for parser/provider/retrieval stack selection.
- req: `{ industry_ids?: string[], document_sample_size: 20|50, parser_providers[], embedding_models[], retrieval_profiles[], metrics?: string[] }`
- res 202: `{ evaluation_run_id, benchmark_type:"poc_stack_benchmark", status_url }`

### GET /v1/evaluations/poc-runs/{evaluation_run_id}
- res 200: `{ status, benchmark_type, parser_results, retrieval_results, metrics:{ recall_at_5, recall_at_10, exact_code_lookup_success_rate, citation_accuracy, spreadsheet_cell_citation_accuracy, groundedness, insufficient_evidence_correct_rejection_rate, high_risk_gate_compliance, parser_table_structure_accuracy, p95_latency_ms, query_cost }, hard_gates:{ acl_leakage_count, tenant_leakage_count, deleted_document_searchable_count, raw_context_logging_violation_count }, recommendation, fallback_paths }`

### POST /v1/feedback
- req: `{ answer_id, rating, comment? }` → 回答・引用に紐づけ保存（FR-027）。

## Versioning

- パスに `/v1`。後方非互換変更は `/v2` を追加し旧版契約を維持（FR-020）。
- レスポンスに `api_version`、deprecation は `Deprecation`/`Sunset` ヘッダで通知。
