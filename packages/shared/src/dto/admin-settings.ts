import type { LoggingPolicy } from "../policy/logging-policy.js";
import type { ProviderPolicy } from "../policy/provider-policy.js";
import type { QueryProfile } from "../policy/query-profile.js";
import type { RetrievalProfile } from "../policy/retrieval-profile.js";

export type DataSourceType =
  | "upload"
  | "object_storage"
  | "confluence"
  | "database"
  | "notion"
  | "box"
  | "google_drive";
export type AdminStatus = "active" | "draft" | "archived";

export interface AdminDataSource {
  source_id: string;
  tenant_id: string;
  collection_id: string;
  type: DataSourceType;
  config: Record<string, unknown>;
  sync_schedule?: string | null;
  last_synced_at?: string | null;
  status: AdminStatus;
  created_at?: string;
  updated_at?: string;
  audit_events?: ProviderConfigAuditEvent[];
}

export interface DataSourceUpsertRequest {
  collection_id: string;
  type: DataSourceType;
  config?: Record<string, unknown>;
  credentials?: Record<string, unknown>;
  sync_schedule?: string | null;
  status?: AdminStatus;
  reason?: string;
}

export type DataSourceProfileType = "auto" | "manufacturing" | "faq" | "manual" | "generic";

export interface DataSourceMappingProfile {
  profile_type?: DataSourceProfileType;
  data_profile?: DataSourceProfileType;
  field_mapping?: Record<string, string>;
  mapping?: Record<string, string>;
  defaults?: Record<string, unknown>;
  required_fields?: string[];
}

export interface DataSourcePreviewRequest {
  collection_id?: string;
  limit?: number;
  sample_documents?: number;
  sample_rows?: number;
  profile_type?: DataSourceProfileType;
  data_profile?: DataSourceProfileType;
  mapping_profile?: DataSourceMappingProfile;
  field_mapping?: Record<string, string>;
  defaults?: Record<string, unknown>;
  required_fields?: string[];
}

export interface DataSourcePreviewRowValidation {
  status: "valid" | "needs_review";
  errors: string[];
  warnings: string[];
}

export interface DataSourcePreviewSampleRow {
  document_id: string;
  sheet_name: string;
  row_number: number;
  raw: Record<string, unknown>;
  normalized: Record<string, unknown>;
  validation: DataSourcePreviewRowValidation;
}

export interface DataSourcePreviewDocument {
  document_id: string;
  document_ref: string;
  content_type: string;
  kind: "table" | "text";
  sample_row_count: number;
  text_preview?: string;
}

export interface DataSourcePreviewProfileOption {
  profile_type: DataSourceProfileType;
  label: string;
}

export interface DataSourcePreviewCanonicalSection {
  label: string;
  fields: string[];
}

export interface DataSourcePreviewResponse {
  source_id: string;
  profile_type: Exclude<DataSourceProfileType, "auto">;
  profile_label: string;
  profile_options: DataSourcePreviewProfileOption[];
  canonical_sections: DataSourcePreviewCanonicalSection[];
  document_count: number;
  documents: DataSourcePreviewDocument[];
  canonical_fields: string[];
  detected_columns: string[];
  explicit_mapping: Record<string, string>;
  suggested_mapping: Record<string, string>;
  mapping_confidence: Record<string, number>;
  defaults: Record<string, unknown>;
  required_fields: string[];
  sample_rows: DataSourcePreviewSampleRow[];
  validation: {
    valid_count: number;
    needs_review_count: number;
    error_count: number;
    warning_count: number;
    errors: string[];
    warnings: string[];
  };
}

export interface QueryProfileSettings extends QueryProfile {
  query_rewrite_enabled?: boolean;
  self_eval_enabled?: boolean;
  self_eval_criteria?: string[];
  embedding_provider?: string;
  llm_provider?: string;
  llm_model?: string;
  captioning_enabled?: boolean;
  captioning_budget_limit?: number | null;
  audit_events?: ProviderConfigAuditEvent[];
}

export interface QueryProfileUpsertRequest extends Partial<QueryProfileSettings> {
  reason?: string;
}

export interface ProviderPolicySettings extends ProviderPolicy {
  allowed_parser_providers?: string[];
  allowed_ocr_providers?: string[];
  allowed_layout_providers?: string[];
  allowed_structured_providers?: string[];
  allowed_llm_providers?: string[];
  allowed_embedding_providers?: string[];
  allowed_visual_embedding_providers?: string[];
  allowed_vlm_providers?: string[];
  allowed_caption_providers?: string[];
  allowed_rerank_providers?: string[];
  provider_regions?: Record<string, unknown>;
  data_residency_requirement?: string;
  provider_contract_refs?: string[];
  provider_capability_snapshot?: Record<string, unknown>;
  fallback_policy?: Record<string, unknown>;
  audit_events?: ProviderConfigAuditEvent[];
}

export interface ProviderPolicyUpsertRequest extends Partial<ProviderPolicySettings> {
  reason?: string;
}

export interface ProviderPolicyValidationRequest {
  collection_id?: string;
  document_sample_refs?: string[];
  operation:
    | "parse"
    | "ocr"
    | "layout"
    | "structured"
    | "embed"
    | "embedding"
    | "visual_embedding"
    | "rerank"
    | "llm"
    | "vlm"
    | "caption"
    | "log";
  provider?: string;
}

export interface ProviderPolicyValidationResponse {
  allowed: boolean;
  reasons: string[];
  required_opt_in?: boolean;
  effective_provider?: string;
  fallback_provider?: string;
}

export interface RetrievalProfileSettings extends RetrievalProfile {
  version?: number;
  keyword_match_enabled?: boolean;
  keyword_strategy?: "postgres_fts" | "pg_bigm" | "pgroonga" | "opensearch" | "disabled";
  vector_score_threshold?: number;
  rerank_provider?: string;
  rerank_model?: string;
  exact_candidate_limit?: number;
  hybrid_candidate_limit?: number;
  audit_events?: ProviderConfigAuditEvent[];
}

export interface RetrievalProfileUpsertRequest extends Partial<RetrievalProfileSettings> {
  reason?: string;
}

export interface RetrievalProfileBenchmarkRequest {
  eval_set_id?: string;
  industry_id?: string;
  sample_size?: number;
  compare_to_profile_id?: string;
}

export interface RetrievalProfileBenchmarkResponse {
  evaluation_run_id: string;
  status_url: string;
}

export interface LoggingPolicySettings extends LoggingPolicy {
  high_risk_trace_policy?: string;
  pii_redaction_policy_ref?: string;
  secret_redaction_policy_ref?: string;
  retention_policy_ref?: string;
  audit_events?: ProviderConfigAuditEvent[];
}

export interface LoggingPolicyUpsertRequest extends Partial<LoggingPolicySettings> {
  reason?: string;
}

export type ACLScopeType = "tenant" | "collection" | "document";
export type ACLSubjectType = "user" | "group" | "role";

export interface AdminACLGrant {
  grant_id: string;
  tenant_id: string;
  scope_type: ACLScopeType;
  scope_id: string;
  subject_type: ACLSubjectType;
  subject_id: string;
  permission: "read";
  created_at?: string;
}

export interface ACLSettingsRequest {
  grants?: Array<Omit<AdminACLGrant, "tenant_id" | "created_at"> & { tenant_id?: string }>;
  revoke_grant_ids?: string[];
  reason?: string;
}

export interface ACLSettingsResponse {
  grants: AdminACLGrant[];
  provider_config_audit_event_id?: string;
}

export type BudgetScopeType = "tenant" | "collection" | "query" | "job";

export interface AdminBudget {
  budget_id: string;
  tenant_id: string;
  scope_type: BudgetScopeType;
  scope_id: string;
  limit: number | null;
  spent?: number;
  currency?: string;
  period?: "daily" | "monthly" | "none";
  status?: AdminStatus;
  updated_at?: string;
}

export interface BudgetSettingsRequest {
  budgets?: Array<Omit<AdminBudget, "tenant_id" | "spent" | "updated_at"> & { tenant_id?: string }>;
  reason?: string;
}

export interface BudgetSettingsResponse {
  budgets: AdminBudget[];
  provider_config_audit_event_id?: string;
}

export interface ProviderConfigAuditEvent {
  provider_config_audit_event_id: string;
  tenant_id: string;
  collection_id?: string;
  event_type:
    | "provider_policy_changed"
    | "retrieval_profile_changed"
    | "logging_policy_changed"
    | "model_changed"
    | "parser_provider_changed"
    | "residency_override"
    | "opt_in_changed"
    | "query_profile_changed"
    | "data_source_changed"
    | "acl_changed"
    | "budget_changed";
  actor: string;
  redacted_before: Record<string, unknown>;
  redacted_after: Record<string, unknown>;
  reason?: string;
  approval_ref?: string;
  created_at: string;
  correlation_id?: string;
}

export type AdminSettingsMutationResponse<T> = T & {
  provider_config_audit_event_id: string;
};
