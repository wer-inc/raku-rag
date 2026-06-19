import type { PolicyLifecycle } from "./lifecycle.js";

export interface QueryProfile extends PolicyLifecycle {
  profile_id: string;
  tenant_id: string;
  collection_id?: string;
  score_threshold: number;
  top_k: number;
  minimum_evidence_count: number;
  rerank_enabled: boolean;
  rerank_top_n: number;
  retrieval_profile_id?: string;
}
