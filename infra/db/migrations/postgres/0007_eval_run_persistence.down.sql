-- Down for 0007: drop the eval-run persistence columns + trend index (non-destructive to the
-- pre-0007 metrics/security_checks columns from 0002).
DROP INDEX IF EXISTS idx_evaluation_runs_trend;

ALTER TABLE evaluation_runs
  DROP COLUMN IF EXISTS probes_executed,
  DROP COLUMN IF EXISTS probe_results,
  DROP COLUMN IF EXISTS baseline_comparison,
  DROP COLUMN IF EXISTS gate_result,
  DROP COLUMN IF EXISTS baseline,
  DROP COLUMN IF EXISTS eval_set_id;
