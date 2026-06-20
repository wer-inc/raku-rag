import type { PolicyLifecycle } from "./lifecycle.js";

export type ParserMode =
  | "aws_only"
  | "azure_document_intelligence_allowed"
  | "google_document_ai_allowed"
  | "customer_managed_parser"
  | "oss_only";

/** No-train / zero-retention is the default (RT11). External cloud needs explicit opt-in. */
export interface ProviderPolicy extends PolicyLifecycle {
  provider_policy_id: string;
  tenant_id: string;
  collection_id?: string;
  name: string;
  status: "active" | "draft" | "archived";
  parser_mode: ParserMode;
  allowed_parser_providers?: string[];
  allowed_ocr_providers?: string[];
  allowed_llm_providers?: string[];
  allowed_embedding_providers?: string[];
  allowed_rerank_providers?: string[];
  allowed_regions?: string[];
  no_train_required: boolean;
  zero_retention_required: boolean;
  cross_cloud_processing_allowed: boolean;
  customer_opt_in_required: boolean;
  customer_opt_in_status?: "pending" | "granted" | "revoked";
  fallback_policy?: Record<string, unknown>;
}
