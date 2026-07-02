-- 0045: S3 upload provenance — server-issued upload records.
--
-- /api/upload/presign registers every presigned object here BEFORE handing the browser a PUT URL,
-- and /internal/ingest resolves `upload_id` -> (bucket, key) from this record instead of trusting a
-- caller-supplied raw `s3://` ref. Records are one-time-use (consumed_at) and expire, so a leaked
-- ref cannot be replayed into another ingest. Standard tenant RLS posture — no cross-tenant escape.
SET search_path TO public;

CREATE TABLE IF NOT EXISTS upload_records (
  tenant_id text NOT NULL,
  upload_id text NOT NULL,
  user_id text NOT NULL DEFAULT '',
  bucket text NOT NULL,
  object_key text NOT NULL,
  content_type text NOT NULL DEFAULT '',
  content_length bigint,
  filename text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  consumed_at timestamptz,
  consumed_by_run text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, upload_id)
);

ALTER TABLE upload_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE upload_records FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_upload_records ON upload_records;
CREATE POLICY tenant_isolation_upload_records
  ON upload_records
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON upload_records TO raku_app;
