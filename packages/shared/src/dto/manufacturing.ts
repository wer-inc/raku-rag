// Manufacturing read-view contracts (specs/014) — consumed by the workspace Operations view.
// Shapes mirror the backend audit-derived views (src/raku_rag/manufacturing/api/dashboard.py,
// kpi/poc_metrics.py, api/policy.py). All values are reference IDs / aggregates — never raw content.

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
