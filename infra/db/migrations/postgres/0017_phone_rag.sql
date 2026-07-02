-- 022-ai-phone-rag: tenant-scoped call sessions, handoff packages, scenarios, QA reviews.
-- (tasks.md T006/T025 named this 0016; 0016 was already taken by chatbot_source_exposure_policies,
--  so the phone tables land as 0017 — numbering must stay contiguous per migration discipline.)
SET search_path TO public;

CREATE TABLE IF NOT EXISTS phone_call_sessions (
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  call_id text NOT NULL,
  correlation_id text NOT NULL,
  channel text NOT NULL DEFAULT 'simulator',
  provider text NOT NULL DEFAULT 'deterministic-simulator',
  caller_phone_number_masked text NOT NULL DEFAULT '',
  customer_id text NOT NULL DEFAULT '',
  state text NOT NULL DEFAULT 'ringing'
    CHECK (state IN ('ringing', 'active', 'on_hold', 'handoff_pending', 'transferred',
                     'completed', 'abandoned', 'failed')),
  intent text NOT NULL DEFAULT '',
  scenario_id text NOT NULL DEFAULT '',
  scenario_version_id text NOT NULL DEFAULT '',
  summary text NOT NULL DEFAULT '',
  resolution_status text NOT NULL DEFAULT '',
  handoff_required boolean NOT NULL DEFAULT false,
  handoff_reason text NOT NULL DEFAULT '',
  handoff_destination text NOT NULL DEFAULT '',
  handoff_package_id text NOT NULL DEFAULT '',
  recording_enabled boolean NOT NULL DEFAULT false,
  recording_disclosure_played boolean NOT NULL DEFAULT false,
  transcript_redaction_status text NOT NULL DEFAULT 'not_needed'
    CHECK (transcript_redaction_status IN ('not_needed', 'redacted', 'flagged', 'failed')),
  turns jsonb NOT NULL DEFAULT '[]'::jsonb,
  started_at timestamptz NOT NULL DEFAULT now(),
  answered_at timestamptz,
  ended_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, call_id)
);

CREATE INDEX IF NOT EXISTS idx_phone_call_sessions_recent
  ON phone_call_sessions (tenant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_phone_call_sessions_intent
  ON phone_call_sessions (tenant_id, intent, state);

CREATE TABLE IF NOT EXISTS phone_handoff_packages (
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  handoff_package_id text NOT NULL,
  call_id text NOT NULL,
  status text NOT NULL DEFAULT 'created'
    CHECK (status IN ('created', 'queued', 'accepted', 'failed', 'unavailable',
                      'abandoned', 'callback_requested')),
  reason text NOT NULL,
  priority text NOT NULL DEFAULT 'normal'
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
  destination_type text NOT NULL DEFAULT 'queue',
  destination_id text NOT NULL DEFAULT 'general-support',
  caller_phone_number_masked text NOT NULL DEFAULT '',
  customer_id text NOT NULL DEFAULT '',
  intent text NOT NULL DEFAULT '',
  summary text NOT NULL DEFAULT '',
  transcript_excerpt_redacted text NOT NULL DEFAULT '',
  confirmed_slots jsonb NOT NULL DEFAULT '{}'::jsonb,
  citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  sentiment text NOT NULL DEFAULT '',
  recommended_next_action text NOT NULL DEFAULT '',
  operator_id text NOT NULL DEFAULT '',
  accepted_at timestamptz,
  failure_reason text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, handoff_package_id)
);

CREATE INDEX IF NOT EXISTS idx_phone_handoff_packages_call
  ON phone_handoff_packages (tenant_id, call_id);
CREATE INDEX IF NOT EXISTS idx_phone_handoff_packages_status
  ON phone_handoff_packages (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS phone_call_scenarios (
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  scenario_id text NOT NULL,
  name text NOT NULL,
  intent text NOT NULL DEFAULT 'faq',
  description text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'in_review', 'approved', 'scheduled', 'published', 'archived')),
  active_version_id text NOT NULL DEFAULT '',
  owner_group text NOT NULL DEFAULT '',
  created_by text NOT NULL DEFAULT '',
  versions jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, scenario_id)
);

CREATE TABLE IF NOT EXISTS phone_quality_evaluations (
  tenant_id text NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  evaluation_id text NOT NULL,
  call_id text NOT NULL,
  reviewer_id text NOT NULL,
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  answer_correctness integer,
  tone_score integer,
  handoff_appropriateness integer,
  compliance_issue boolean NOT NULL DEFAULT false,
  hallucination_detected boolean NOT NULL DEFAULT false,
  privacy_issue boolean NOT NULL DEFAULT false,
  suggested_fix text NOT NULL DEFAULT '',
  knowledge_gap_topics text[] NOT NULL DEFAULT ARRAY[]::text[],
  review_status text NOT NULL DEFAULT 'open'
    CHECK (review_status IN ('open', 'actioned', 'dismissed')),
  improvement_item_id text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, evaluation_id)
);

CREATE INDEX IF NOT EXISTS idx_phone_quality_evaluations_call
  ON phone_quality_evaluations (tenant_id, call_id);

-- RLS: same tenant-isolation posture as every other tenant table (deny-by-default).
ALTER TABLE phone_call_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE phone_call_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE phone_handoff_packages ENABLE ROW LEVEL SECURITY;
ALTER TABLE phone_handoff_packages FORCE ROW LEVEL SECURITY;
ALTER TABLE phone_call_scenarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE phone_call_scenarios FORCE ROW LEVEL SECURITY;
ALTER TABLE phone_quality_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE phone_quality_evaluations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_phone_call_sessions ON phone_call_sessions;
CREATE POLICY tenant_isolation_phone_call_sessions
  ON phone_call_sessions
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_phone_handoff_packages ON phone_handoff_packages;
CREATE POLICY tenant_isolation_phone_handoff_packages
  ON phone_handoff_packages
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_phone_call_scenarios ON phone_call_scenarios;
CREATE POLICY tenant_isolation_phone_call_scenarios
  ON phone_call_scenarios
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation_phone_quality_evaluations ON phone_quality_evaluations;
CREATE POLICY tenant_isolation_phone_quality_evaluations
  ON phone_quality_evaluations
  USING (tenant_id = raku.current_tenant_id())
  WITH CHECK (tenant_id = raku.current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON phone_call_sessions TO raku_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON phone_handoff_packages TO raku_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON phone_call_scenarios TO raku_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON phone_quality_evaluations TO raku_app;
