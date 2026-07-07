SET search_path TO public;

DROP POLICY IF EXISTS tenant_isolation_extraction_quarantine_chunks
  ON extraction_quarantine_chunks;
DROP INDEX IF EXISTS idx_extraction_quarantine_review_status;
DROP INDEX IF EXISTS idx_extraction_quarantine_tenant_document;
DROP TABLE IF EXISTS extraction_quarantine_chunks;
