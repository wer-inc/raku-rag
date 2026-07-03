SET search_path TO public;

ALTER TABLE manufacturing_document_metadata
  DROP COLUMN IF EXISTS owner,
  DROP COLUMN IF EXISTS review_cycle_days,
  DROP COLUMN IF EXISTS last_verified_at;
