import type { PolicyLifecycle } from "./lifecycle.js";

/** Vector-only retrieval is forbidden as the default (ADR-005). */
export interface RetrievalProfile extends PolicyLifecycle {
  retrieval_profile_id: string;
  tenant_id: string;
  collection_id?: string;
  name: string;
  status: "active" | "draft" | "archived";
  metadata_filter_required: boolean;
  identifier_match_enabled: boolean;
  identifier_fields: string[];
  vector_search_enabled: boolean;
  vector_top_k: number;
  rerank_enabled: boolean;
  rerank_candidate_limit: number;
  final_context_limit: number;
  max_context_tokens: number;
  minimum_evidence_count: number;
  fallback_behavior: "insufficient_evidence" | "vector_only_disabled" | "temporarily_unavailable";
}
