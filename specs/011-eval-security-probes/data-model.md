# Phase 1 Data Model — Eval Security & Injection Probes

Entities are dataclasses in `src/raku_rag/eval/probes.py` unless noted. Additive to `eval/models.py`.

## SecurityProbe (protocol/interface)

A named, executable security check that converts tested behavior into a count.

| Member | Type | Notes |
|---|---|---|
| `name` | `str` | one of `SECURITY_CHECKS` (e.g. `acl_leakage`) |
| `run(harness) -> ProbeResult` | callable | builds its scenario on the harness, executes leak + positive-control, returns a result |

- MUST be deterministic and stdlib-only.
- MUST include a positive control; if the control fails, return `status="unavailable"` (fail closed, research D3).

## ProbeResult (frozen dataclass)

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | `str` | — | probe name |
| `executed` | `bool` | `False` | True once the probe ran (provenance) |
| `leakage_count` | `int` | `0` | observed leaks; `> 0` ⇒ block |
| `status` | `str` | `"ok"` | `ok` \| `blocked` \| `unavailable` |
| `reason` | `str` | `""` | redacted, human-readable; empty when ok |

`to_dict()` → `{name, executed, leakage_count, status, reason}`.

## SecurityProbeSuite

Orchestrates the five probes against ephemeral harnesses.

| Member | Type | Notes |
|---|---|---|
| `probes` | `tuple[SecurityProbe, ...]` | the five, default-constructed |
| `run() -> SuiteOutcome` | callable | builds harness(es), runs each probe, aggregates |

`SuiteOutcome`:
| Field | Type | Notes |
|---|---|---|
| `results` | `tuple[ProbeResult, ...]` | one per probe |
| `counts` | `dict[str, int]` | `{name: leakage_count}` — fed to the runner |
| `probes_executed` | `bool` | True iff all probes report `executed` (provenance, FR-007) |

- Harness construction: fresh `MvpSystem()` for `acl_leakage`/`deleted_reappearance`/`tenant_isolation`/`prompt_injection`; `ManufacturingSystem()` for `source_poisoning`. Each probe gets a clean scenario (no cross-probe state).
- A probe raising/`unavailable` ⇒ `probes_executed=False` and the suite still returns (the runner will block on it).

## EvaluationRun (existing — extended, additive)

`src/raku_rag/eval/models.py` — new optional fields, defaults keep all current callers/serialization valid:

| New field | Type | Default | Notes |
|---|---|---|---|
| `probe_results` | `tuple[dict, ...]` | `()` | `ProbeResult.to_dict()` per probe |
| `probes_executed` | `bool` | `False` | provenance; the anti-regression guard asserts this is True for production-caller runs |

`to_dict()` extended to include both. `security_checks` and `gate_result` semantics unchanged in shape.

## Runner integration (`runner.py`) — behavior contract

- `EvaluationRunner.__init__` gains an optional `probe_suite: SecurityProbeSuite | None = None` (defaults to the standard suite). Injectable for tests.
- In `run()`: execute `probe_suite.run()` → `outcome`. Compute
  `effective = {name: max(outcome.counts.get(name,0), (security_check_counts or {}).get(name,0)) for name in SECURITY_CHECKS}`.
- `security_checks = _security_checks(effective)`; `gate_result = "blocked"` if any check fails **or** `not outcome.probes_executed` (D3/D4).
- Attach `probe_results=outcome.results-as-dicts`, `probes_executed=outcome.probes_executed` to the `EvaluationRun`.

## AdversarialFixture (data, `tests/fixtures/eval/adversarial.json`)

| Field | Type | Notes |
|---|---|---|
| `kind` | `str` | `injection` \| `poisoning` |
| `chunk_text` | `str` | synthetic adversarial content |
| `expected_safe_outcome` | `str` | what "no leak" looks like (answer unchanged / poisoned not primary) |

No real PII/secrets; passed through `Redactor` defensively.

## Invariants

1. `SECURITY_CHECKS` (incl. new `prompt_injection`, `source_poisoning`) is the single source of probe names; `_security_checks` and `baseline_from_run` derive from it.
2. Caller `security_check_counts` can only **raise** an effective count (research D2) — preserves the protected test.
3. `probes_executed=False` ⇒ `gate_result="blocked"` (fail closed).
