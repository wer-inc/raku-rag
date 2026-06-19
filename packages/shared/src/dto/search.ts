export interface SearchRequest {
  query: string;
  collection_id?: string;
  top_k?: number;
}

export interface Freshness {
  indexed_at: string | null;
  document_version: number | null;
  source_freshness?: string | null;
}

export interface SearchResultItem {
  source_id: string;
  document_id: string;
  chunk_id: string;
  version: number;
  retrieval_score: number;
  heading_path: string[];
  text?: string;
  freshness: Freshness;
}

export interface SearchResponse {
  results: SearchResultItem[];
  correlation_id: string;
}
