// Manufacturing read-view contracts (specs/014) — consumed by the workspace Operations + Sources
// views. Shapes mirror the backend audit-derived views (src/raku_rag/manufacturing/api/dashboard.py,
// kpi/poc_metrics.py, api/policy.py) and knowledge views (knowledge/trouble_cases.py, the
// answer-service source-sync / ingestion-run serializers). All values are reference IDs / aggregates
// or candidate/reference knowledge — never raw confidential content.

import type { Citation } from "./answer.js";

/** GET /v1/manufacturing/dashboard — KnowledgeOpsDashboard (FR-MFG-012). */
export interface KnowledgeOpsDashboard {
  unanswered_question_count: number;
  low_rating_answers: string[];
  frequent_questions: string[];
  frequently_referenced_documents: string[];
  obsolete_document_candidates: string[];
  knowledge_gap_areas: string[];
  correlation_id: string;
}

/** GET /v1/manufacturing/safety-telemetry — SafetyTelemetryView (FR-MFG-030). */
export interface SafetyTelemetryView {
  tenant_id: string;
  high_risk_query_count: number;
  safety_gate_block_count: number;
  /** block reason -> count; `safety_gate_block_breakdown` is the contract alias. */
  block_breakdown?: Record<string, number>;
  safety_gate_block_breakdown?: Record<string, number>;
  axis?: Record<string, string | null>;
  time_range?: { from: string | null; to: string | null; granularity: string };
  source: string;
  correlation_id: string;
}

/** GET /v1/manufacturing/kpi — the FR-MFG-028 PoC KPI set (json). Extra keys allowed. */
export interface ManufacturingKpi {
  self_resolution_rate: number;
  average_time_to_answer: { p50: number; p95: number };
  grounded_answer_rate: number;
  insufficient_evidence_rate: number;
  low_rating_rate: number;
  unanswered_question_count: number;
  frequently_referenced_documents: string[];
  obsolete_document_candidates: string[];
  expert_interruption_reduction: number;
  high_risk_query_count: number;
  safety_gate_block_count: number;
  materialized_at: string;
  source?: string;
  source_ingestion_run_id?: string;
  dagster_run_id?: string;
  [key: string]: unknown;
}

/** GET /v1/manufacturing/governance/status — AI-governance core features + ISMAP memo (FR-MFG-024~026). */
export interface GovernanceStatus {
  tenant_id: string;
  policy_version: string | number;
  no_train: {
    no_train_default: boolean;
    training_opt_in: boolean;
    provider_no_train_required: boolean;
    no_train_fallback: string;
  };
  audit_coverage: { tamper_evident: boolean; reference_ids_only: boolean };
  safety_gate: { enabled: boolean; high_risk_requires_approved_citation: boolean };
  draft_review: { ai_output_always_draft: boolean; reviewer_required_for_approval: boolean };
  groundedness: { enabled: boolean; citation_required: boolean };
  retention: { retention_customer_days: number; retention_audit_days: number };
  ismap_readiness_memo?: string;
  [key: string]: unknown;
}

// --- Sources view (specs/014 slice 2) ----------------------------------------------------------

/** POST /v1/manufacturing/trouble-cases/search request. */
export interface TroubleCaseSearchRequest {
  symptom_query: string;
  collection_id?: string;
  manufacturing_filters?: Record<string, unknown>;
  top_k?: number;
}

export interface FailureModeView {
  tenant_id: string;
  failure_mode_id: string;
  name: string;
  description: string;
}

/**
 * A past-case countermeasure as displayed. Hard Rule 4: `type` is always `candidate` and `label`
 * marks it as a past-example candidate/reference — it is NEVER a definitive/official work order.
 */
export interface DisplayCountermeasure {
  measure_id: string;
  description: string;
  /** display/evidence axis — `candidate` for any past-case measure. */
  type: "candidate" | "reference" | string;
  /** nature axis, preserved: provisional | permanent | unknown. */
  measure_class: "provisional" | "permanent" | "unknown" | string;
  /** past-example candidate label (never a definitive instruction). */
  label: string;
}

export interface CountermeasureSplit {
  provisional: DisplayCountermeasure[];
  permanent: DisplayCountermeasure[];
}

export interface TroubleCaseMatch {
  trouble_case_id: string;
  symptom: string;
  equipment_id: string | null;
  process_id: string | null;
  failure_mode: FailureModeView | null;
  countermeasures: CountermeasureSplit;
  recurrence_prevention: string | null;
  citations: Citation[];
  relevance_score: number;
}

/** Past trouble-cases are shown as candidates/reference (FR-MFG-008/009, Hard Rule 4). */
export interface TroubleCaseSearchResponse {
  status: "ok" | "insufficient_evidence" | string;
  results: TroubleCaseMatch[];
  correlation_id: string;
}

// Source sync-status / ingestion-run for the MANUFACTURING routes use a distinct serializer
// (src/raku_rag/manufacturing/api/ingest_metadata.py -> control_plane SourceSyncStatusProjection)
// whose shape differs from the generic ingest endpoints: counts are nested under `summary`, the last
// ingestion-run id is carried as `correlation_id`, and per-document state uses `status` (not
// index_status). These manufacturing-specific DTOs match that real shape — do NOT reuse the generic
// SourceSyncStatusResponse / IngestionRunStatusResponse, which describe the other serializer.

export interface ManufacturingProcessingStateDoc {
  document_id: string;
  status: string;
  chunk_count?: number;
  failure_reason?: string;
  source_id?: string;
  collection_id?: string;
  updated_at?: string;
  [key: string]: unknown;
}

/** Source-sync count rollup (nested under `summary`). */
export interface ManufacturingSyncSummary {
  observed_count?: number;
  changed_count?: number;
  deleted_count?: number;
  skipped_count?: number;
  failed_count?: number;
}

/** GET /v1/manufacturing/sources/{id}/sync-status — `status` is "not_found" for an unknown id. */
export interface ManufacturingSourceSyncStatus {
  tenant_id: string;
  source_id: string;
  collection_id?: string;
  status: string;
  last_manifest_checksum?: string;
  summary: ManufacturingSyncSummary;
  documents: ManufacturingProcessingStateDoc[];
  /** carries the last ingestion-run id. */
  correlation_id?: string;
  [key: string]: unknown;
}

/** GET /v1/manufacturing/documents — tenant document inventory row. */
export interface ManufacturingDocumentSummary {
  document_id: string;
  collection_id: string;
  source_id: string;
  document_kind: string | null;
  approval_status: string;
  effective_date: string | null;
  approved_by: string | null;
  approved_at: string | null;
  superseded_by: string | null;
  equipment: string | null;
  safety_category: string | null;
}

/** Ingestion-run count rollup (nested under `summary`). */
export interface ManufacturingRunSummary {
  document_count?: number;
  succeeded_count?: number;
  failed_count?: number;
}

/** GET /v1/manufacturing/ingestion-runs/{id} — `status` is "not_found" for an unknown id. */
export interface ManufacturingIngestionRun {
  ingestion_run_id: string;
  tenant_id: string;
  collection_id?: string;
  source_id?: string;
  document_id?: string;
  type?: string;
  trigger?: string;
  status: string;
  failure_reason?: string;
  chunk_count?: number;
  started_at?: string;
  finished_at?: string;
  summary?: ManufacturingRunSummary;
  documents: ManufacturingProcessingStateDoc[];
  [key: string]: unknown;
}

// --- Reviews view (specs/014 slice 3) — the human review loop -----------------------------------

export type DraftStatus = "draft" | "in_review" | "approved" | "rejected" | "archived" | string;
export type DraftType =
  | "checklist"
  | "trouble_report"
  | "quality_report"
  | "training"
  | "faq"
  | string;

/**
 * An AI- or user-authored draft (data-model §F). Default `status="draft"` is the central safety
 * invariant: AI output is ALWAYS draft and cannot transition past draft automatically — only a human
 * reviewer approves (Hard Rule 1 / SC-MFG-007).
 */
export interface DraftArtifact {
  tenant_id: string;
  artifact_id: string;
  type: DraftType;
  collection_id: string | null;
  status: DraftStatus;
  source_citations: string[];
  source_document_ids: string[];
  template_id: string | null;
  created_by: "ai" | "user" | null;
  created_at: string | null;
  audit_log_ref: string | null;
  reviewer_id: string | null;
  reviewer_role: string | null;
  reviewer_group: string | null;
  assigned_at: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  approval_decision: "approve" | "reject" | string | null;
  review_status: string | null;
  content: Record<string, unknown>;
}

export interface CreateDraftRequest {
  kind: DraftType;
  source_document_ids?: string[];
  template_id?: string;
  collection_id?: string;
  manufacturing_filters?: Record<string, unknown>;
}

export interface AssignReviewerRequest {
  reviewer_id?: string;
  reviewer_group?: string;
  reviewer_role?: string;
}

export interface ReviewDraftRequest {
  /** Backend `_VALID_DECISIONS`: a draft transitions to this terminal status. */
  decision: "approved" | "rejected" | "archived" | string;
  comment?: string;
}

/** POST /v1/manufacturing/documents/{id}/approval — reviewer-driven approval state transition. */
export interface DocumentApprovalRequest {
  to_status?: "draft" | "pending_review" | "approved" | "obsolete" | string;
  import_external?: Record<string, unknown>;
}

export interface DocumentApprovalResult {
  document_id: string;
  approval_state: unknown;
}

/** GET /v1/manufacturing/drafts — tenant draft inventory. */
export interface DraftListResponse {
  drafts: DraftArtifact[];
}

/** GET /v1/admin/documents — tenant document inventory with approval metadata. */
export interface AdminDocumentListResponse {
  documents: ManufacturingDocumentSummary[];
}

export interface DocumentChunkSummary {
  chunk_id: string;
  text: string;
  position: number;
  heading_path: string[];
  metadata: Record<string, unknown>;
}

/** GET /v1/admin/documents/:id — document detail for review / citation. */
export interface AdminDocumentDetail {
  document_id: string;
  collection_id: string;
  source_id: string;
  document_kind: string | null;
  approval_status: string;
  effective_date: string | null;
  approved_by: string | null;
  approved_at: string | null;
  superseded_by: string | null;
  equipment: string | null;
  safety_category: string | null;
  chunk_count: number;
  chunks: DocumentChunkSummary[];
}

/** GET /v1/admin/documents/:id/citation-view — citation viewer payload. */
export interface CitationSourceView {
  document_id: string;
  collection_id: string;
  source_id: string;
  approval_status: string;
  effective_date: string | null;
  superseded_by: string | null;
  document_kind: string | null;
  chunks: DocumentChunkSummary[];
  preview?: CitationPreview;
}

/** GET /v1/manufacturing/audit/events — paginated audit browser. */
export interface AuditEventListResponse {
  events: Record<string, unknown>[];
  total: number;
  offset: number;
  limit: number;
}

export interface CitationPreview {
  kind: "text" | "spreadsheet" | "pdf" | "word" | string;
  content_type: string;
  sheet_name?: string;
  row?: number;
  col?: number;
  cell_range?: string;
  heading_path?: string[];
  page_number?: number;
  has_source_file?: boolean;
}

export interface ImprovementQueueItem {
  id: string;
  kind: string;
  answer_id: string | null;
  document_ids: string[];
  reason: string | null;
  created_at: string;
  rating?: number | null;
  safety_block_reason?: string | null;
}

export interface ImprovementQueueResponse {
  items: ImprovementQueueItem[];
  total: number;
  correlation_id: string;
}

export interface DocumentFileResponse {
  document_id: string;
  content_type: string;
  size: number;
  content_base64?: string;
  too_large?: boolean;
}
