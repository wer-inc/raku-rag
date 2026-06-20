export interface FeedbackRequest {
  answer_id?: string;
  evaluation_run_id?: string;
  subject: "user" | "eval_job";
  rating: 1 | 2 | 3 | 4 | 5;
  comment?: string;
}

export interface FeedbackResponse {
  feedback_id: string;
  status: "accepted";
}
