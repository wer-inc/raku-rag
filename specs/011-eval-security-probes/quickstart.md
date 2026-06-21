# Quickstart — Validate Eval Security & Injection Probes

Runnable validation that the eval gate now **computes** its security signal. Stdlib-only; no cloud/Docker.

## Prerequisites
- Repo root, `PYTHONPATH=src`. No external services.

## Scenarios

### S1 — Probes run and a clean system passes
```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_eval_probes_run -v
```
Expected: a real eval run reports `probes_executed == True`, all five `security_checks` present with `count == 0`, `gate_result == "passed"`, and each probe's positive control holds.

### S2 — Each planted leak blocks the gate (the fix)
```bash
PYTHONPATH=src python3 -m unittest tests.security.test_eval_security_probes -v
```
Expected: for each of `acl_leakage`, `deleted_reappearance`, `tenant_isolation`, `prompt_injection`, `source_poisoning`, a planted leak ⇒ `gate_result == "blocked"` and that check `passed == False`.

### S3 — A no-op probe cannot pass (positive control)
Covered in S2: replacing a probe with an all-deny/no-op stub makes its positive-control assertion fail (the gate cannot be satisfied by returning nothing).

### S4 — Caller override still blocks (protected test unchanged)
```bash
PYTHONPATH=src python3 -m unittest tests.security.test_eval_hard_gate -v
```
Expected: GREEN, unmodified — `security_check_counts={name:1}` still yields `blocked` (merge-by-max preserves it).

### S5 — Anti-regression: probes must actually run
```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_ci_eval_gate -v
```
Expected: fails if a production-caller run reports `probes_executed == False` or empty `probe_results`.

### S6 — Full gate stays green and fast
```bash
time scripts/gate.sh a          # Tier A — expect GREEN, sub-second
scripts/gate.sh separation      # expect "separation OK" (gate-def change committed separately)
```

## Done when
- S1–S6 pass; the eval-gate jobs in `.github/workflows/ci.yml` (eval-gate) and `gate.yml` exercise the probes; `docs/production-readiness/loop-state.md` records the loop and the gate-design review.
