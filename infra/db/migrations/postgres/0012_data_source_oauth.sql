-- 021-gdrive: durable per-tenant OAuth connections for the Google Drive connector.
--
-- FORWARD-LOOKING. The runtime source of truth this PR is the in-memory OAuthConnectionStore in the
-- answer-service (mirroring the in-memory admin/datasource store); this table is the durable home for
-- when connection persistence is wired to Postgres. The refresh token itself NEVER lives here — only a
-- SecretStore reference (refresh_token_secret_ref); the token is in AWS Secrets Manager (KMS-encrypted).

-- Pin the target schema like every domain migration (0001-0010). Without this the unqualified CREATE
-- lands in whatever the session search_path happens to be, where the answer-service connection
-- (search_path=public) cannot resolve it.
SET search_path TO public;

CREATE TABLE IF NOT EXISTS data_source_oauth (
  connection_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  source_id text NOT NULL DEFAULT '',
  provider text NOT NULL DEFAULT 'google_drive',
  refresh_token_secret_ref text NOT NULL,
  scope text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'revoked', 'error')),
  created_at text,
  updated_at text
);

-- One active connection per (tenant, source); the partial predicate lets multiple pre-save
-- connections (source_id = '') coexist before a datasource binds them.
CREATE UNIQUE INDEX IF NOT EXISTS data_source_oauth_tenant_source_uq
  ON data_source_oauth (tenant_id, source_id)
  WHERE source_id <> '';

CREATE INDEX IF NOT EXISTS data_source_oauth_tenant_idx
  ON data_source_oauth (tenant_id);

ALTER TABLE data_source_oauth ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_source_oauth FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS data_source_oauth_tenant_isolation ON data_source_oauth;
CREATE POLICY data_source_oauth_tenant_isolation
  ON data_source_oauth
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON data_source_oauth TO raku_app;
