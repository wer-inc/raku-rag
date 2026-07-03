-- ★G3a: answer_feedback — durable 👍/👎 answer feedback (admin 改善キュー server-driven).
--
-- POST /v1/feedback previously landed in an in-memory dict inside the answer-service
-- (_EvalFeedbackStore), so every restart erased the feedback and the admin improvement queue
-- had to be reconstructed from browser localStorage. This table persists each rating with its
-- reason category. Comments are PII-redacted with the observability Redactor BEFORE write
-- (same stance as audit_logs); rating keeps both the raw 1-5 score and the up/down/neutral
-- taxonomy the queue filters on. Standard tenant RLS posture; no cross-tenant escape.
SET search_path TO public;

CREATE TABLE IF NOT EXISTS answer_feedback (
  feedback_id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  correlation_id text NOT NULL DEFAULT '',
  evaluation_run_id text NOT NULL DEFAULT '',
  subject text NOT NULL DEFAULT 'user' CHECK (subject IN ('user', 'eval_job')),
  rating text NOT NULL DEFAULT 'neutral' CHECK (rating IN ('up', 'down', 'neutral')),
  score integer NOT NULL DEFAULT 0,
  reason_code text NOT NULL DEFAULT '',
  comment text NOT NULL DEFAULT '',
  actor_id text NOT NULL DEFAULT '',
  citation_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_answer_feedback_tenant_created
  ON answer_feedback (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_answer_feedback_tenant_rating
  ON answer_feedback (tenant_id, rating);

ALTER TABLE answer_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_feedback FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_answer_feedback ON answer_feedback;
CREATE POLICY tenant_isolation_answer_feedback
  ON answer_feedback
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT ON answer_feedback TO raku_app;
