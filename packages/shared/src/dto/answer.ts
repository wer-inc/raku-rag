import type { Freshness } from "./search.js";

export type AnswerStatus =
  | "ok"
  | "insufficient_evidence"
  | "budget_exceeded"
  | "temporarily_unavailable";

export interface Citation {
  kind: "text" | "visual";
  document_id: string;
  chunk_id: string | null;
  source_id: string;
  version: number;
  /** [start, end) code-point offsets in the source for text citations */
  text_range?: [number, number];
  retrieval_score: number;
}

export interface UsedChunk {
  chunk_id: string;
  document_id: string;
  retrieval_score: number;
}

export interface AnswerRequest {
  query: string;
  collection_id?: string;
}

export interface AnswerResponse {
  status: AnswerStatus;
  text: string | null;
  citations: Citation[];
  used_chunks: UsedChunk[];
  confidence: number | null;
  freshness: Freshness | null;
  correlation_id: string;
}
