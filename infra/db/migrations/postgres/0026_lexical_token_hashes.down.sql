DROP INDEX IF EXISTS idx_documents_identifier_compacts_unbackfilled;
DROP INDEX IF EXISTS idx_chunks_identifier_compacts_unbackfilled;
DROP INDEX IF EXISTS idx_documents_identifier_compacts_live;
DROP INDEX IF EXISTS idx_chunks_identifier_compacts_live;
ALTER TABLE documents DROP COLUMN IF EXISTS identifier_compacts;
ALTER TABLE chunks DROP COLUMN IF EXISTS identifier_compacts;
DROP INDEX IF EXISTS idx_chunks_lexical_tokens_unbackfilled;
DROP INDEX IF EXISTS idx_chunks_lexical_token_hashes_live;
ALTER TABLE chunks DROP COLUMN IF EXISTS lexical_token_hashes;
-- intarray is intentionally left installed: dropping a shared extension on rollback could break
-- unrelated objects; removing the column and indexes fully reverts this migration's effect.
