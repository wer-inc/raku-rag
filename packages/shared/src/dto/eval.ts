export interface EvaluationExpectedEvidence {
  document_id: string;
  chunk_id?: string;
}

export interface EvaluationSetItem {
  item_id?: string;
  question: string;
  expected_answer?: string;
  expected_evidence: EvaluationExpectedEvidence[];
}

export interface EvaluationSetCreateRequest {
  items: EvaluationSetItem[];
}

export interface EvaluationSetCreateResponse {
  eval_set_id: string;
  item_count: number;
  status: "created";
}

export interface EvaluationRunCreateRequest {
  eval_set_id: string;
  baseline?: boolean;
  collection_id?: string;
}

export interface EvaluationRunCreateResponse {
  run_id: string;
  status_url: string;
}

export interface EvaluationRunStatusResponse {
  run_id: string;
  eval_set_id: string;
  tenant_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  baseline: boolean;
  metrics: Record<string, number>;
  baseline_comparison: Record<string, number>;
  security_checks: Record<string, { passed: boolean; count: number }>;
  gate_result: "passed" | "blocked";
  created_at?: string;
}
