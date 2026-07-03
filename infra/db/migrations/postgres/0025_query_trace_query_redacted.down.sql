SET search_path TO public;

ALTER TABLE query_traces DROP COLUMN IF EXISTS query_redacted;
