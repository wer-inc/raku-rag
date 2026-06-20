# The 6 Absolute Hard Gates (SC-MFG-006..011)

The manufacturing layer has **six absolute hard gates** — zero-tolerance mechanism-pins per
`docs/loop-engineering.md` §3. Each is a named test file under `tests/manufacturing/`, runs in Tier A
of `scripts/gate.sh`, and is in the script's **protected set** (it may not be modified together with
`src/` in one change — §5 separation guard). They are the gates CI runs on every push.

## The six gates

| SC | What it pins | Test file | Key entrypoints / mechanism |
|----|--------------|-----------|------------------------------|
| **SC-MFG-006** | High-risk classifier **recall on danger** + the **approved-citation-required** block with its exact reason code. | `tests/manufacturing/test_safety_gate.py` | `RuleHighRiskClassifier.classify`, `ManufacturingSafetyGate.evaluate`. High-risk + no approved+effective citation ⇒ `status="insufficient_evidence"`, `safety_block_reason="approved_citation_missing"`, no asserted text, `used_chunks=()`. Includes a **positive control** (approved+effective ⇒ `ok`, asserts) and a **precision negative control** (benign query not over-flagged) so a degenerate always-block impl cannot pass; ambiguous ⇒ fail-safe high-risk. |
| **SC-MFG-007** | AI output is **always draft** and only a **human reviewer** reaches `approved` (Hard Rule 1). | `tests/manufacturing/test_draft_only.py` | `generate_draft` (always `status=draft`, `created_by=ai`, all 5 kinds incl. FAQ), `review_draft` (no reviewer ⇒ rejected/stays draft; direct status mutation not honored by the system of record), positive control (a reviewer **can** approve, attributable). |
| **SC-MFG-008** | Department / factory / role / equipment-area access as a **mapping onto the 001 ACL**, not a new authz path. Leakage = 0. | `tests/manufacturing/test_acl_mapping.py` | `ManufacturingSystem.grant_scope` → `acl_mapping.apply_scope` / `grants_for_scope`. Confidential doc absent from search / answer-citation / draft for an unauthorized user; the confidential chunk is excluded **before scoring** (asserts `store.last_prefiltered_count` — pre-, not post-filter); cross-tenant rejected via `enforce_same_tenant`; positive control (authorized user **can** see it). |
| **SC-MFG-009** | **No-train**: customer data never used for training without an explicit opt-in; an un-guaranteed capability is **blocked, not silently degraded** (GQ1). | `tests/manufacturing/test_no_train.py` | `use_for_training` (rejects without opt-in; 0 accepted uses by default), `no_train.capability_allowed` / `capability_status` (`temporarily_unavailable`), `resolve_capability_provider` (never a leaky provider). Positive controls: a no-train-guaranteed capability is allowed; opt-in **with** `opt_in_contract_ref` permits training; opt-in is tenant-scoped. |
| **SC-MFG-010** | **Audit coverage** = 100% (closed enumeration), **PII = 0**, **tamper-evident** SHA-256 hash chain. | `tests/manufacturing/test_audit_coverage.py` | Drives an end-to-end flow and asserts every category in `REQUIRED_EVENT_TYPES` (ingest/parse/metadata, approval, draft generate + review, high-risk decision, safety_gate block, answer, citation access, ACL denied, policy change, deletion) appears. No customer name / body / secret in any stored entry. `audit.verify_chain(principal)` is `True`, and mutating a stored entry breaks it. |
| **SC-MFG-011** | **Obsolete / draft documents are never primary evidence** for an asserted answer (with the mandatory obsolete warning). | `tests/manufacturing/test_obsolete_draft_evidence.py` | `ManufacturingSafetyGate` (single-doc: obsolete/draft-only ⇒ not `ok`, `obsolete_warning`) **and** the `ManufacturingAnswerService.answer` multi-doc **demote** (an obsolete top citation with no approved+effective among cited evidence ⇒ `insufficient_evidence`, the T066 capstone class). Positive control: an approved+effective doc answers with no warning. |

## What each gate pins, by file

- **`test_safety_gate.py` (SC-MFG-006)** drives `ManufacturingSystem.answer`. It enumerates a labeled
  high-risk intent set (every one must flag), a metadata-tagged variant, the approved-citation-missing
  block (asserting the **reason code**, not merely "no text"), an expired/not-yet-effective date case,
  the positive control, the ambiguous fail-safe, and the precision + non-high-risk-scope controls.
- **`test_draft_only.py` (SC-MFG-007)** drives `generate_draft` / `assign_reviewer` / `review_draft` /
  `get_draft`. It asserts the rejection of AI self-approve (both a no-reviewer `review_draft` call and
  a direct dataclass `status` mutation leave the system-of-record artifact `draft`), and FAQ parity.
- **`test_acl_mapping.py` (SC-MFG-008)** seeds a confidential factory-B doc and proves 0 leakage via
  `grant_scope`, asserting the pre-filter count (`self.sys._mvp.store.last_prefiltered_count`) — the
  same mechanism the 001 `tests/security/test_tenant_isolation.py` case5 pins.
- **`test_no_train.py` (SC-MFG-009)** constructs `ManufacturingSystem(provider_capabilities=...,
  no_train_providers=...)` and exercises `use_for_training`, `no_train.assert_no_train` /
  `capability_allowed` / `capability_status`, `resolve_capability_provider`,
  `update_data_use_policy` (opt-in invariant).
- **`test_audit_coverage.py` (SC-MFG-010)** is the broadest: `_drive_end_to_end(sys)` exercises
  ingest → approval → draft generate+review → high-risk answer (asserting + blocked) → ACL denial →
  policy change → deletion, then checks the closed `REQUIRED_EVENT_TYPES` list, PII = 0, and the hash
  chain (`verify_chain` + a mutation breaking it).
- **`test_obsolete_draft_evidence.py` (SC-MFG-011)** covers the single-doc gate **and** the multi-doc
  demote (`TestObsoletePrimaryWithUnrelatedApprovedCoexisting`).

## How `scripts/gate.sh` + CI enforce them

`scripts/gate.sh` has three modes:

- **`a` (default, Tier A)** — runs `tests/security/**` (the 001 security hard gates) and, when
  `tests/manufacturing/` exists, the manufacturing test suite (which includes all 6 hard-gate files).
  Zero tolerance: any failure halts. stdlib `unittest`, milliseconds.
- **`all`** — Tier A **plus** the full `tests/` suite (integration + unit).
- **`separation`** — the §5 verification/generation separation invariant.

### The §5 separation guard

`run_separation` blocks the reward-hack shape: **modifying an already-committed protected gate/test
file together with `src/` in one change**. The protected set (regex in the script) is exactly:

```
tests/security/
tests/manufacturing/unit/
tests/manufacturing/test_(safety_gate|obsolete_draft_evidence|draft_only|acl_mapping|no_train|audit_coverage).py
scripts/gate.sh
```

— i.e. the 001 security gates, the 6 named 002 hard-gate files, the unit gate tests, and the gate
script itself. If any of those is **modified** (`--diff-filter=M`) alongside any `src/` change, the
guard exits **3** ("Gate changes must be a separate, independently-reviewed commit"). **Adding** a new
hard-gate test is allowed; only modifying an existing protected file together with `src/` is the
violation. Exit codes: `0` = green, `1` = Tier A test failure (HALT), `3` = separation violation.

CI runs `gate.sh` on every push, so a regression in any of the six gates — or a test+src reward-hack
mix touching a protected file — fails the build before merge.
