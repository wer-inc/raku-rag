/**
 * Manufacturing approval/safety metadata supplied at ingest (mfg-openapi.md). Forwarded verbatim to
 * the answer-service, which persists it on the Document so the safety overlay (high-risk gate,
 * draft/obsolete demotion) fires for production-ingested docs. tenant_id/document_id are NOT taken
 * from here — the server uses the authenticated principal + the request document_id.
 */
export interface ManufacturingIngestMetadata {
  approval_status?: "draft" | "pending_review" | "approved" | "obsolete";
  effective_date?: string | null;
  approval_source?: "imported" | "workflow";
  approved_by?: string;
  approved_at?: string;
  obsolete_at?: string;
  superseded_by?: string;
  document_kind?: string;
  safety_category?: string;
  quality_category?: string;
  equipment_operation_category?: string;
  hazard_tags?: string[];
  equipment_id?: string;
  process_id?: string;
  alarm_code?: string;
  defect_type?: string;
  part_no?: string;
  customer?: string;
  /** ★G4 freshness: responsible person/team for keeping the document current. */
  owner?: string;
  /** ★G4 freshness: review cycle in days (0/absent = no cycle). */
  review_cycle_days?: number;
  /** ★G4 freshness: ISO date of the last human "still correct" verification. */
  last_verified_at?: string;
}

export interface IngestRequest {
  collection_id: string;
  source_id: string;
  document_id: string;
  /**
   * object-storage ref. Production S3 uploads must use tenants/<tenant>/uploads/... refs.
   * Optional when `upload_id` is supplied — the server then resolves bucket/key from the
   * registered upload record (0045) and, if ref is also present, requires them to match.
   */
  ref?: string;
  /** server-issued upload provenance id from POST /v1/uploads (one-time-use, expiring) */
  upload_id?: string;
  content_type?: string;
  /** optional manufacturing approval/safety metadata (drives the safety overlay) */
  manufacturing?: ManufacturingIngestMetadata;
}

/** 0045 — register S3 upload provenance before the browser receives the presigned PUT URL. */
export interface UploadRegisterRequest {
  upload_id: string;
  bucket: string;
  object_key: string;
  content_type?: string;
  content_length?: number;
  filename?: string;
}

export interface UploadRegisterResponse {
  tenant_id: string;
  upload_id: string;
  bucket: string;
  object_key: string;
  content_type: string;
  content_length: number | null;
  filename: string;
  created_at: string;
  expires_at: string;
  consumed_at: string | null;
}

export type IngestionRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled"
  | "partially_succeeded"
  | "dead_letter";

export type SourceSyncStatus =
  | "idle"
  | "queued"
  | "observing"
  | "syncing"
  | "succeeded"
  | "partially_succeeded"
  | "failed";

export interface IngestJob {
  ingestion_run_id: string;
  tenant_id: string;
  collection_id: string;
  source_id: string;
  status: IngestionRunStatus;
}

export interface IngestResponse {
  ingestion_run_id: string;
  document_id: string;
  status: IngestionRunStatus;
  status_url: string;
  sqs_message_id?: string;
  failure_reason?: string;
  chunk_count?: number;
}

export interface DeleteDocumentResponse {
  job_id: string;
  document_id: string;
  status: "succeeded" | "failed";
  tombstoned_chunks: number;
  invalidated_cache_entries: number;
  purged_chunks: number;
  tombstoned_crops?: number;
  invalidated_visual_cache_entries?: number;
  tombstoned_visual_assets?: number;
  tombstoned_visual_regions?: number;
  tombstoned_visual_embeddings?: number;
}

export interface ReindexRequest {
  source_id?: string;
  document_ids?: string[];
  reason?: "parser_version_change" | "chunking_config_change" | "embedding_model_change" | "manual" | "recovery";
  target_parser_version?: string;
  target_chunking_config_version?: string;
  target_embedding_model_version?: string;
}

export interface ReindexResponse {
  reindex_plan_id: string;
  collection_id: string;
  source_id?: string;
  status: "planned" | "running" | "succeeded" | "failed" | "canceled";
  status_url: string;
  affected_document_count: number;
  dagster_backfill_id?: string;
}

export interface IngestionRunSummary {
  observed_count: number;
  changed_count: number;
  deleted_count: number;
  skipped_count: number;
  failed_count: number;
}

export interface AdminJobSummary {
  job_id: string;
  ingestion_run_id?: string;
  type: string;
  trigger?: string;
  status: IngestionRunStatus;
  source_id?: string;
  document_id?: string;
  failure_reason?: string;
  retry_count?: number;
  started_at?: string;
  finished_at?: string;
  dagster_run_id?: string;
  dagster_run_url?: string;
}

export interface IngestionRunStatusResponse {
  ingestion_run_id: string;
  type: string;
  trigger: string;
  status: IngestionRunStatus;
  collection_id?: string;
  source_id?: string;
  document_id?: string;
  retry_count?: number;
  failure_reason?: string;
  started_at?: string;
  finished_at?: string;
  dagster_run_id?: string;
  dagster_run_url?: string;
  summary: IngestionRunSummary;
  documents: DocumentProcessingStatusResponse[];
  asset_materializations?: Array<{
    dagster_asset_key: string;
    partition_key?: string;
    storage_uri?: string;
  }>;
  correlation_id?: string;
}

export interface SourceSyncStatusResponse extends IngestionRunSummary {
  source_id: string;
  collection_id: string;
  status: SourceSyncStatus;
  last_ingestion_run_id?: string;
  freshness?: {
    last_successful_sync_at?: string;
  };
  last_error?: string;
  dagster_run_id?: string;
  dagster_run_url?: string;
}

export interface DocumentProcessingStatusResponse {
  document_id: string;
  source_document_id?: string;
  ingestion_run_id?: string;
  content_checksum?: string;
  parser_version?: string;
  chunking_config_version?: string;
  embedding_model_version?: string;
  parse_status: IngestionRunStatus;
  chunk_status: IngestionRunStatus;
  embedding_status: IngestionRunStatus;
  index_status: IngestionRunStatus;
  last_indexed_at?: string;
  last_error?: string;
  dagster_run_id?: string;
}

/** SQS message contract (P1 worker consumes this); idempotency_key dedupes redelivery. */
export interface IngestionJobMessage {
  idempotency_key: string;
  tenant_id: string;
  collection_id: string;
  source_id: string;
  document_id: string;
  document_ref: string;
  content_type?: string;
}
