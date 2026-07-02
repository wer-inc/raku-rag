-- Sprint1 S1-3: restart-durable ChatBot state (sessions / handoffs / feedback / scenarios).
-- Previously in-memory only — an answer-service restart lost every conversation. Payload-JSONB
-- rows + typed listing columns, RLS-forced, same posture as 0017_phone_rag.
SET search_path TO public;

CREATE TABLE IF NOT EXISTS chatbot_sessions (
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  session_id text NOT NULL,
  user_id text NOT NULL DEFAULT '',
  channel text NOT NULL DEFAULT 'web_chat',
  status text NOT NULL DEFAULT 'active',
  current_intent text NOT NULL DEFAULT '',
  last_message_at timestamptz NOT NULL DEFAULT now(),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_chatbot_sessions_recent
  ON chatbot_sessions (tenant_id, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_chatbot_sessions_status
  ON chatbot_sessions (tenant_id, status, current_intent);

CREATE TABLE IF NOT EXISTS chatbot_handoffs (
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  handoff_id text NOT NULL,
  session_id text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'queued',
  reason text NOT NULL DEFAULT '',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, handoff_id)
);

CREATE INDEX IF NOT EXISTS idx_chatbot_handoffs_session
  ON chatbot_handoffs (tenant_id, session_id);

CREATE TABLE IF NOT EXISTS chatbot_feedback (
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  evaluation_id text NOT NULL,
  session_id text NOT NULL DEFAULT '',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, evaluation_id)
);

CREATE TABLE IF NOT EXISTS chatbot_scenarios (
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  scenario_id text NOT NULL,
  status text NOT NULL DEFAULT 'draft',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, scenario_id)
);

-- RLS: same tenant-isolation posture as every other tenant table (deny-by-default).
ALTER TABLE chatbot_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chatbot_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE chatbot_handoffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE chatbot_handoffs FORCE ROW LEVEL SECURITY;
ALTER TABLE chatbot_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE chatbot_feedback FORCE ROW LEVEL SECURITY;
ALTER TABLE chatbot_scenarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE chatbot_scenarios FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_chatbot_sessions ON chatbot_sessions;
CREATE POLICY tenant_isolation_chatbot_sessions
  ON chatbot_sessions
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_chatbot_handoffs ON chatbot_handoffs;
CREATE POLICY tenant_isolation_chatbot_handoffs
  ON chatbot_handoffs
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_chatbot_feedback ON chatbot_feedback;
CREATE POLICY tenant_isolation_chatbot_feedback
  ON chatbot_feedback
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_chatbot_scenarios ON chatbot_scenarios;
CREATE POLICY tenant_isolation_chatbot_scenarios
  ON chatbot_scenarios
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON chatbot_sessions TO raku_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON chatbot_handoffs TO raku_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON chatbot_feedback TO raku_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON chatbot_scenarios TO raku_app;
