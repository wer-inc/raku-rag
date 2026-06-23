-- P1-7: lexical retrieval leg index.
--
-- The core retrieval path now has a Postgres lexical leg in addition to vector and metadata exact
-- matching. Keep it usable at production corpus size by indexing live chunk text with a language-
-- neutral parser; Japanese production search can later switch to a dedicated analyzer/OpenSearch.

CREATE INDEX IF NOT EXISTS idx_chunks_text_lexical_live
  ON chunks USING gin (to_tsvector('simple', text))
  WHERE tombstone = false;
