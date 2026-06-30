SET search_path TO public;

DROP POLICY IF EXISTS tenant_isolation_chatbot_source_exposure_policies
  ON chatbot_source_exposure_policies;

DROP INDEX IF EXISTS idx_chatbot_source_exposure_collection;

DROP TABLE IF EXISTS chatbot_source_exposure_policies;
