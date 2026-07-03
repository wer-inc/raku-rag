/** ★G3b/★G5: 実測運用メトリクス — real per-query operational metrics from query_traces. */

/** One unanswered/refused query (PII redacted server-side BEFORE persistence). */
export interface QualityRefusalRecord {
  request_id: string;
  /** The question text, already masked by the observability Redactor — never raw PII. */
  query_redacted: string;
  status: string;
  /** ISO timestamp; empty in the deterministic (in-memory) profile. */
  created_at: string;
}

export interface QualityOperationalResponse {
  query_count: number;
  /** Real measured latency percentiles (ms) over query_traces.total_ms. */
  p50_ms: number;
  p95_ms: number;
  avg_total_tokens: number;
  /** Answer status → count (ok / insufficient_evidence / budget_exceeded / ...). */
  status_counts: Record<string, number>;
  /** insufficient_evidence / query_count (0 when no traffic). */
  insufficient_rate: number;
  /** Newest-first drill-down of non-ok queries (未回答分析). */
  recent_refusals: QualityRefusalRecord[];
  /** Persisted 👎 feedback rows (answer_feedback, rating="down"). */
  low_rating_count: number;
}
