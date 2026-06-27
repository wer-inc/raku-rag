import type { Freshness } from "./search.js";
import type { BoundingBoxDto } from "./assets.js";

export type AnswerStatus =
  | "ok"
  | "insufficient_evidence"
  | "budget_exceeded"
  | "temporarily_unavailable";

export interface Citation {
  kind:
    | "text"
    | "visual"
    | "spreadsheet"
    | "table_row"
    | "form_field"
    | "chart_series"
    | "figure_caption";
  document_id: string;
  chunk_id: string | null;
  source_id: string;
  version: number;
  /** [start, end) code-point offsets in the source for text citations */
  text_range?: [number, number];
  retrieval_score: number;
  asset_id?: string | null;
  page_number?: number | null;
  region_id?: string | null;
  bbox?: BoundingBoxDto | null;
  sheet_name?: string | null;
  cell_range?: string | null;
  row_id?: string | null;
  table_id?: string | null;
  form_id?: string | null;
  field_name?: string | null;
  chart_id?: string | null;
  series_name?: string | null;
  point_index?: number | null;
  column_name?: string | null;
  pixel_derived?: boolean;
  visual_evidence_verified?: boolean;
  visual_verifier_verdicts?: Array<Record<string, unknown>>;
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
