export interface FeedbackRequest {
  answer_id?: string;
  evaluation_run_id?: string;
  subject: "user" | "eval_job";
  rating: 1 | 2 | 3 | 4 | 5;
  comment?: string;
  /** ★G3a: structured reason category (改善キュー). Falls back to `reason:<code>` in comment. */
  reason_code?: string;
  /** ★G3a: per-citation verdict target. Falls back to `citation:<id>` in comment. */
  citation_id?: string;
}

export interface FeedbackResponse {
  feedback_id: string;
  status: "accepted";
}

/** ★G3a: one persisted feedback row (answer_feedback, comment PII-redacted server-side). */
export interface FeedbackRecord {
  feedback_id: string;
  tenant_id: string;
  answer_id: string;
  evaluation_run_id: string;
  subject: "user" | "eval_job";
  rating: "up" | "down" | "neutral";
  score: number;
  reason_code: string;
  comment: string;
  actor_id: string;
  citation_id: string | null;
  created_at: string;
}

export interface FeedbackListResponse {
  items: FeedbackRecord[];
}
