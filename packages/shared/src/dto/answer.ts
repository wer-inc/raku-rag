import type { Freshness } from "./search.js";

export type AnswerStatus =
  | "ok"
  | "insufficient_evidence"
  | "budget_exceeded"
  | "temporarily_unavailable";

export interface Citation {
  kind: "text" | "visual" | "spreadsheet";
  document_id: string;
  chunk_id: string | null;
  source_id: string;
  version: number;
  /** [start, end) code-point offsets in the source for text citations */
  text_range?: [number, number];
  retrieval_score: number;
  sheet_name?: string | null;
  cell_range?: string | null;
  row_id?: string | null;
  approval_status?: "draft" | "pending_review" | "approved" | "obsolete" | string;
  effective_date?: string | null;
  approval_source?: string | null;
}

export interface UsedChunk {
  chunk_id: string;
  document_id: string;
  retrieval_score: number;
}

export interface AnswerDisplaySection {
  id: string;
  title: string;
  text?: string;
  fields?: Record<string, unknown>;
  items?: Array<Record<string, unknown>>;
}

export interface AnswerRequest {
  query: string;
  collection_id?: string;
}

export interface ManufacturingAnswerRequest extends AnswerRequest {
  intent_hint?: string;
  manufacturing_filters?: Record<string, unknown>;
}

export interface ManufacturingSafetyExtension {
  high_risk: boolean;
  high_risk_reason_codes: string[];
  safety_block_reason?: string | null;
  obsolete_warning?: boolean;
  requires_onsite_confirmation?: boolean;
  notice?: string | null;
}

export interface AnswerResponse {
  status: AnswerStatus;
  route?: "rag" | "structured_tool" | "refused_structured_tool_required";
  text: string | null;
  citations: Citation[];
  used_chunks: UsedChunk[];
  confidence: number | null;
  freshness: Freshness | null;
  correlation_id: string;
  answer_template_version?: string;
  display_sections?: AnswerDisplaySection[];
}

export interface ManufacturingAnswerResponse extends AnswerResponse {
  manufacturing: ManufacturingSafetyExtension;
}
