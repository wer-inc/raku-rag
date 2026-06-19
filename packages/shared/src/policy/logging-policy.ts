import type { PolicyLifecycle } from "./lifecycle.js";

export type RawStorage = "disabled" | "redacted" | "full_opt_in";

/** OD-008 / ADR-015: raw retrieved context is NEVER stored by default. */
export interface LoggingPolicy extends PolicyLifecycle {
  logging_policy_id: string;
  tenant_id: string;
  collection_id?: string;
  name: string;
  status: "active" | "draft" | "archived";
  raw_user_query_storage: RawStorage; // default "disabled"
  raw_retrieved_context_storage: RawStorage; // default "disabled"
  model_input_storage: RawStorage;
  model_output_storage: RawStorage;
  store_citation_ids: boolean;
  store_chunk_ids: boolean;
  store_prompt_template_version: boolean;
  store_model_metadata: boolean;
  store_latency: boolean;
  store_cost: boolean;
  production_sampling_rate: number;
}

export const LOGGING_POLICY_DEFAULTS: Pick<
  LoggingPolicy,
  "raw_user_query_storage" | "raw_retrieved_context_storage" | "model_input_storage" | "model_output_storage"
> = {
  raw_user_query_storage: "disabled",
  raw_retrieved_context_storage: "disabled",
  model_input_storage: "disabled",
  model_output_storage: "disabled",
};
