export interface IngestRequest {
  collection_id: string;
  source_id: string;
  /** object-storage ref (MinIO/S3) or inline upload id */
  ref: string;
  content_type?: string;
}

export type IngestionRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled"
  | "partially_succeeded";

export interface IngestJob {
  ingestion_run_id: string;
  tenant_id: string;
  collection_id: string;
  source_id: string;
  status: IngestionRunStatus;
}

/** SQS message contract (P1 worker consumes this); idempotency_key dedupes redelivery. */
export interface IngestionJobMessage {
  idempotency_key: string;
  tenant_id: string;
  collection_id: string;
  source_id: string;
  document_ref: string;
  content_type?: string;
}
