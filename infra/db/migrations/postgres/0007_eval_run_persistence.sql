-- 0007 (P2-9): persist full evaluation runs so eval results are trendable across releases.
-- Additive ALTER of evaluation_runs (created in 0002, already tenant-scoped + RLS-forced there; the
-- new columns inherit that row-level security). Adds the gate decision, baseline comparison, eval set
-- linkage, and the probe provenance the runner now produces. Per-item `examples` are intentionally
-- NOT persisted (the table is for metric/gate/provenance trending, not per-item replay).
ALTER TABLE evaluation_runs
  ADD COLUMN IF NOT EXISTS eval_set_id text,
  ADD COLUMN IF NOT EXISTS baseline boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS gate_result text NOT NULL DEFAULT 'passed',
  ADD COLUMN IF NOT EXISTS baseline_comparison jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS probe_results jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS probes_executed boolean NOT NULL DEFAULT false;

-- Trend index: newest-first listing per (tenant, eval set) for cross-release comparison.
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_trend
  ON evaluation_runs (tenant_id, eval_set_id, created_at DESC);
