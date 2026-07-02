-- ★V2: tenant_lexicon — per-tenant vocabulary/message overrides (industry flexibility).
--
-- Hardcoded industry vocabulary (high-risk safety keywords, chat/phone handoff triggers, canned
-- messages) resolves as DEFAULTS ⊕ tenant overrides from this table. Merging is ADDITIVE by
-- construction for keyword namespaces — defaults are never removed, so a tenant can extend
-- danger detection but never weaken it. Standard tenant RLS posture; no cross-tenant escape.
SET search_path TO public;

CREATE TABLE IF NOT EXISTS tenant_lexicon (
  tenant_id text NOT NULL,
  namespace text NOT NULL,
  key text NOT NULL,
  values jsonb NOT NULL DEFAULT '[]'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, namespace, key)
);

ALTER TABLE tenant_lexicon ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_lexicon FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_tenant_lexicon ON tenant_lexicon;
CREATE POLICY tenant_isolation_tenant_lexicon
  ON tenant_lexicon
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_lexicon TO raku_app;
