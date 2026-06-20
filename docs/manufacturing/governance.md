# Governance — No-Train, Retention, Tamper-Evident Audit, and APIs

The governance overlay enforces the AI-governance hard rules: customer data is **never** used for
training without an explicit opt-in (GQ1 = block, not silent degrade), retention defaults to 365/365
days (GQ2), and every governance/safety/access event lands in a **tamper-evident, reference-IDs-only**
audit log. It reuses the 001 deletion/tombstone, the 001 `Redactor`, and 001 tenancy — it owns the
*policy*, not the mechanism.

## DataUsePolicy + store (`governance/no_train.py`, `domain/policy.py`)

`InMemoryDataUsePolicyStore` is per-tenant and auto-seeds the GQ1/GQ2 safe-posture `default_policy`
on first access (`policy_version="1"`):

| Field | Default | Rule |
|-------|---------|------|
| `no_train_default` | `True` | FR-MFG-016 |
| `training_opt_in` | `False` | FR-MFG-018 |
| `opt_in_contract_ref` | `None` | required when opt-in is `True` |
| `provider_no_train_required` | `True` | FR-MFG-017 |
| `no_train_fallback` | `BLOCK` | GQ1 |
| `retention_customer` | `365` | GQ2 |
| `retention_audit` | `365` | GQ2 |
| `export_enabled` | `False` | — |

`update(tenant_id, patch, actor)` applies a partial patch over `_PATCHABLE_FIELDS`, **bumps
`policy_version`** on every accepted change (FR-MFG-019), and enforces the opt-in invariant: `_validate`
raises `ValueError` if `training_opt_in=True` without a non-empty `opt_in_contract_ref` (FR-MFG-018),
leaving the stored policy unchanged. `tenant_id` / `policy_version` are owned by the store, never the
patch; an unknown patch field raises.

## No-train guard (`governance/no_train.py`)

Provider no-train *capability verification* is Base CR-001-B's job; `InMemoryNoTrainGuard` enforces the
**002 policy** against an **injected** provider-capability map (`provider_capabilities`,
`no_train_providers`). When the caller injects none, `app.py` applies a safe local default
(`mvp_local` treated as no-train-guaranteed for `answer_llm` / `embedding` / `ocr` / `draft_llm`).

- `assert_no_train(tenant_id, data_kind)` **raises** `NoTrainViolation` (a `PermissionError`) unless
  the tenant has `training_opt_in=True` **and** a non-empty `opt_in_contract_ref`. The default policy
  refuses (SC-MFG-009 = 0 accepted training uses without opt-in).
- `capability_allowed(tenant_id, capability)` is `False` when `provider_no_train_required` is set and
  **no** available provider for the capability is in the injected no-train-guaranteed set (GQ1 = block);
  `True` when at least one is.
- `capability_status(...)` surfaces `"ok"` (`CAPABILITY_OK`) or `"temporarily_unavailable"`
  (`CAPABILITY_BLOCKED`) — GQ1 = capability-origin block, never an inferred answer.
- `resolve_capability_provider(...)` returns a no-train-guaranteed provider or `None` when blocked —
  **never** a non-no-train provider (no silent degrade).

`ManufacturingSystem` funnels all training use through `use_for_training(*, tenant_id, data_kind,
actor)`: it calls `no_train.assert_no_train(...)` **before** any use (so opt-in-less training is
impossible), audits the attempt as `permitted` / `refused` (action `no_train.training_use`, a
reference label only), and re-raises on refusal. `capability_status(...)` /
`resolve_capability_provider(...)` are also surfaced on the system.

## Retention (`governance/retention.py`)

`InMemoryRetentionManager` builds **no new deletion mechanism**: it owns the policy (how long) and
delegates expiry to the reused 001 `DeletionService` (tombstone + cascade, SC-003).

- `effective_retention(tenant_id) -> RetentionConfig` returns the tenant's effective retention
  (default 365/365, GQ2). An override from `DataUsePolicy` is **clamped** into the advisory guide band
  `RETENTION_MIN_DAYS = 30` .. `RETENTION_MAX_DAYS = 3650` (a misconfiguration fails safe to the bounded
  value, not a hard reject).
- `expire_document(tenant_id, document_id)` delegates to the 001 tombstone path; a deleted document
  never reappears in search/answer/citation (SC-003). Raises if no `DeletionService` is wired.

## Tamper-evident audit log (`domain/audit.py`)

`AuditLogEntry` is the tenant-scoped structured record (data-model §H). It carries **reference IDs
only** — never PII / secret / confidential body text — plus a safety/approval snapshot
(`high_risk_classification_result`, `safety_block_reason`, `approval_status_at_use`), evidence refs
(`citation_ids`, `document_ids_used`), the org-context snapshot (`factory_id`, `department_id`), and
the hash-chain fields (`prev_hash`, `entry_hash`).

`InMemoryAuditLogWriter` is the **single source of truth** telemetry/KPI derive from:

- **Reference IDs only + redaction**: on `record(...)` it runs every free-text field
  (`_REDACT_TEXT_FIELDS` = `action`, `reason`, `decision`, `source_ip`, `actor_role`, `actor_group`)
  and every string in `client_metadata` through the reused 001 `Redactor` as defence-in-depth
  (SC-MFG-010 = PII 0). Reference-ID / hash fields are **not** redacted (they are opaque identifiers).
- **Tenant isolation**: an untenanted entry is rejected (`TenantIsolationError`). `read_all(principal)`
  is scoped to the principal's tenant; `read_for_tenant(principal, tenant_id)` calls
  `enforce_same_tenant` so any cross-tenant aggregation fails closed.
- **Hash chain (Base CR-001-A)**: on `record(...)`, `prev_hash` = the previous entry's `entry_hash`
  (per-tenant chain), and `entry_hash = compute_entry_hash(...)` — a SHA-256 over every field except
  `entry_hash` (including `prev_hash`, so a re-order is also detected), using stdlib `hashlib` (no new
  dependency). `verify_chain(principal)` returns `True` iff every `prev_hash` links and every
  `entry_hash` recomputes; mutating any stored field without re-hashing makes it return `False`.

The org-context helpers `actor_org_context(principal, factory_id=...)` and `stamp_org_context(entry,
principal, factory_id=...)` derive `(factory_id, department_id)` from the **same** FR-MFG-013 mapping
as the ACL (department == the actor's primary 001 ACL group, falling back to role; factory == the
caller-supplied territory) and snapshot them immutably at write time for US5 telemetry grouping.

## Governance / export APIs (`api/policy.py`)

`GovernanceService` is the in-memory analog of the §F/§G endpoints, surfaced on `ManufacturingSystem`:

- `get_data_use_policy(tenant_id)` — GET `/v1/manufacturing/policy/data-use`; auto-seeds the GQ1/GQ2
  default.
- `update_data_use_policy(*, tenant_id, patch, actor)` — PUT `.../policy/data-use`; applies the patch
  (opt-in invariant enforced, version bumped) and audits the change. The audit action is labelled by
  patch keys: `policy.no_train.change` / `policy.retention.change` / `policy.setting.change`; the
  `reason` records the changed setting **names** only — never the contract-ref value.
- `governance_status(tenant_id)` — GET `.../governance/status`; presents the core AI-governance
  features + the `ISMAP_READINESS_MEMO`. The memo is explicitly "designed-with-ISMAP-in-view" and
  **must not** claim registration / full compliance (FR-MFG-025/026).
- `export_audit(*, principal, fmt="jsonl")` — GET `.../audit/export`; tenant-scoped, reference-only,
  exposes the `prev_hash`/`entry_hash` chain so a downstream importer can re-verify tamper-evidence.
  Formats: `jsonl` / `csv` / `dict`. The 001 `Redactor` is re-applied at the export boundary (verbatim
  set: `resource_id`, `citation_ids`, `document_ids_used`, hashes, ids). The admin export is itself
  audited (`audit.export`).

`ManufacturingSystem.delete_document(*, tenant_id, document_id, actor)` deletes via the reused 001
tombstone (`self._mvp.deletion.delete`) and audits the deletion (action `deletion.tombstone`,
reference ID only). A deleted document never reappears (SC-003).

## Base CR notes pointer

- **Base CR-001-A** — the 001 audit base extended here (hash chain + reference-IDs-only redaction).
- **Base CR-001-B** — the production verified no-train provider-capability set, injected into the
  guard's `provider_capabilities` / `no_train_providers`; 002 enforces the opt-in/GQ1 **policy**
  locally against that injected set.
