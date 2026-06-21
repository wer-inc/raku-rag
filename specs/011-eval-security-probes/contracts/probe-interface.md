# Contract — Security Probe Interface & Gate Semantics

Internal contract for `src/raku_rag/eval/probes.py` ↔ `src/raku_rag/eval/runner.py`. This is the **gate contract** — changes require human review (`loop-engineering.md §3/§5`).

## SecurityProbe

```
class SecurityProbe(Protocol):
    name: str                       # ∈ SECURITY_CHECKS
    def run(self) -> ProbeResult:   # builds its own ephemeral harness, executes, returns
        ...
```

Contract:
- **Deterministic, stdlib-only, no external service, no network.**
- **Self-contained scenario**: the probe constructs its own ephemeral system (in-memory `MvpSystem` / `ManufacturingSystem`); it MUST NOT touch the live system-under-eval (research D1).
- **Positive control mandatory**: the probe MUST verify the authorized/benign path works; if it does not, return `status="unavailable"` (fail closed). This blocks the "all-deny passes" reward hack.
- **Leakage counting**: `leakage_count` = number of observed unauthorized exposures (0 ⇒ ok). Any value > 0 ⇒ the check fails.
- **Redaction**: `reason` MUST be redacted (no raw secrets/PII), via `observability/redaction.py`.

## ProbeResult / SuiteOutcome

```
ProbeResult(name, executed: bool, leakage_count: int, status: "ok"|"blocked"|"unavailable", reason: str)
SuiteOutcome(results: tuple[ProbeResult,...], counts: dict[str,int], probes_executed: bool)
```

## Gate semantics (runner)

Given probe `counts` and optional caller `security_check_counts`:

```
effective[name] = max(counts.get(name, 0), caller.get(name, 0))   for name in SECURITY_CHECKS
security_checks[name] = {passed: effective[name] == 0, count: effective[name]}
gate_result = "blocked" if (any not passed) or (not probes_executed) else "passed"
```

**Preserved invariants (MUST NOT regress):**
1. Caller-supplied count `{name: n>0}` ⇒ `blocked` and `security_checks[name].count == n` — keeps `tests/security/test_eval_hard_gate.py` green **unmodified**.
2. A probe-found leak (`counts[name] > 0`) ⇒ `blocked` even when caller passes `0` (the fix).
3. `probes_executed == False` ⇒ `blocked` (fail closed).
4. Existing metrics, `baseline_comparison`, `examples`, and `EvaluationRun` shape are unchanged except the additive `probe_results` / `probes_executed` fields.

## Production caller contract (FR-006/FR-007)

- `apps/answer-service/server.py` `_EvalFeedbackStore.create_run` and `dagster/jobs/evaluation.py` `execute_evaluation_job` MUST cause the probe suite to run (default `EvaluationRunner` runs it), and the resulting `EvaluationRun.probes_executed` MUST be `True`.
- CI assertion (`tests/unit/test_ci_eval_gate.py` additive + `tests/integration/test_eval_probes_run.py`): a run from a production caller with `probes_executed == False` is a CI failure.

## Acceptance (mirrors spec SC-001..SC-006)

- Planted leak in each of the 5 categories ⇒ `gate_result == "blocked"` (per-category test).
- Clean harness ⇒ all counts 0, `probes_executed == True`, gate passes; positive controls hold.
- No-op/all-deny probe stub ⇒ positive-control assertion fails (cannot pass by returning nothing).
- Caller `{name:1}` still blocks (protected test unchanged).
- Tier A stays green and sub-second.
