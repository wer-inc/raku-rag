-- ★G3b: query_traces.query_redacted — the (already PII-redacted) question text per trace.
--
-- 未回答分析 (which questions went unanswered, goal.md ★G5 実測メトリクス) needs the question
-- itself; 0022 deliberately stored no query text at all, so traces could not drive the drill-down.
-- The value is masked by the observability Redactor BEFORE the write (same stance as chatbot
-- session transcripts and answer_feedback comments) — raw PII never reaches this column. The
-- 0022 identity posture is unchanged: identities stay hashed, no answer/context text is stored.
SET search_path TO public;

ALTER TABLE query_traces ADD COLUMN IF NOT EXISTS query_redacted text NOT NULL DEFAULT '';
