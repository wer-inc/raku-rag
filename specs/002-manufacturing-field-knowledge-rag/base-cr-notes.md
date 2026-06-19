# Base Change Requests (CR-001-A..D) — 001 integration notes

**Task:** T065 (Phase 9 — Governance Overlay).
**Scope:** document the four Base Change Requests the manufacturing solution layer (002) depends on
from the generic RAG platform (001). 002 does **not** redefine 001 base features; cross-cutting
governance requirements are raised as **Base CR-001-A..D** and delegated to 001. This note records,
per CR, (1) what 001 must provide for production, (2) what 002 implements **locally / minimally** in
the in-memory MVP so the Phase-9 hard gates (SC-MFG-009 / SC-MFG-010) can close now, and (3) the
responsibility boundary so the 001 work does not duplicate or weaken the 002 enforcement.

Authoritative sources: `spec.md` §FR-MFG-016..029, "Base CR-001-A..D", GQ1/GQ2; `research.md` R9/R10/
R11/R13; `plan.md` Constitution check III/IV/VIII + "Base Change Request の取り扱い"; `data-model.md`
§G/§H; `contracts/mfg-openapi.md` §F/§G; `contracts/mfg-interfaces.md` §7/§8.

---

## CR-001-A — Audit / Observability extension (tamper-evidence, export, retention link)

**001 (platform) must provide:** extend the base audit/trace facility ([base:FR-016/023]) into a
structured, durable `AuditLogEntry` store with a **tamper-evident hash chain**, tenant-scoped reads
(no cross-tenant reference), export, and a retention hook — so every product-layer event
(FR-MFG-021) is recorded consistently by the platform.

**002 (this layer) implements locally / minimally (Phase 9):**
- `manufacturing/domain/audit.py` — `AuditLogEntry` schema is **reference-IDs-only** (no PII / secret
  / body text; SC-MFG-010 = 0) and the 001 `Redactor` runs at write time as defence-in-depth.
- Tamper-evidence: `InMemoryAuditLogWriter.record` now links each entry into a per-tenant **SHA-256
  `prev_hash`/`entry_hash` chain** (`hashlib`, stdlib; additive, default-safe fields), and
  `verify_chain(principal)` recomputes the chain and detects any in-place mutation. `compute_entry_hash`
  hashes every field except `entry_hash` (including `prev_hash`, so re-ordering also breaks it).
- 100% coverage of the SC-MFG-010 event taxonomy is wired through `ManufacturingSystem`: ingest/parse/
  metadata, approval transition, draft generate/assign/review, high-risk decision, safety-gate block,
  answer, **citation access**, **ACL denial**, no-train/retention policy change, deletion/tombstone.
  (ACL-denial auditing observes the SAME 001 deny-by-default pre-filter decision — no new authz.)
- Export: `manufacturing/api/policy.py::GovernanceService.export_audit` (jsonl / csv / dict),
  tenant-scoped, reference-only (Redactor re-applied at the export boundary), exposes the
  `prev_hash`/`entry_hash` chain for downstream re-verification.

**Boundary / hand-off to 001:** 002's in-memory chain + reference-only schema is the contract the
production platform store must honour. 001 owns durable storage, the production export endpoint, and
the retention-driven purge (see CR-001-C). 001 must NOT weaken the reference-IDs-only or
tamper-evidence guarantees when it backs them with a real datastore.

---

## CR-001-B — Provider no-train capability and configuration verification

**001 (platform) must provide:** add a **data-use mode / no-train capability** to the provider
abstraction ([base:FR-031], LLM/VLM/Embedding/OCR) — declaration, enforcement and **verification**
metadata — plus provider config storage and provider audit-log linkage. 001 owns *whether a provider
is genuinely no-train-guaranteed* (the verified set) and persists provider configuration.

**002 (this layer) implements locally / minimally (Phase 9):**
- `manufacturing/governance/no_train.py::InMemoryNoTrainGuard` enforces the **002 policy** against an
  **injected** provider-capability map. The verified no-train set is *injected* (Base CR-001-B's
  output); 002 does not itself verify a provider.
  - `assert_no_train(tenant, data_kind)` raises unless `training_opt_in=True` AND a non-empty
    `opt_in_contract_ref` (FR-MFG-018) — the single funnel `ManufacturingSystem.use_for_training`
    delegates to it before any use, so opt-in-less training is impossible (SC-MFG-009 = 0).
  - `capability_allowed(tenant, capability)` is **False** when `provider_no_train_required` and no
    available provider for the capability is in the injected no-train set → GQ1 = **BLOCK**, surfaced
    as `capability_status == "temporarily_unavailable"`. `resolve_capability_provider` NEVER returns a
    non-no-train provider for a blocked capability (no silent degrade).
- `ManufacturingSystem(provider_capabilities=..., no_train_providers=...)` injects the map; when
  omitted a safe local default (`mvp_local`, treated as no-train-guaranteed) keeps built capabilities
  available while still routing every decision through the guard.

**Boundary / hand-off to 001:** 002 = policy / opt-in / governance presentation; 001 = provider
no-train **configuration verification**, config persistence, provider audit linkage (G5, FR-MFG-029).
The injected `no_train_providers` set is the production output of 001's verification; 002 must keep
treating any provider absent from that set as NOT no-train-guaranteed (block by default).

---

## CR-001-C — Data retention / export

**001 (platform) must provide:** add tenant data **export** and a **configurable retention policy**
to the base data lifecycle ([base:FR-007/008]); deletion reuses the existing tombstone/cascade.

**002 (this layer) implements locally / minimally (Phase 9):**
- `DataUsePolicy.retention_customer` / `retention_audit` defaults **365 / 365 days** (GQ2),
  tenant-overridable; guide range **30..3650 days** (out-of-range overrides clamp into the band).
- `manufacturing/governance/retention.py::InMemoryRetentionManager.effective_retention` resolves the
  effective values; `expire_document` **delegates** removal to the reused 001 `DeletionService`
  (tombstone + cascade) — no new deletion mechanism (a deleted doc never reappears; SC-003).
- Audit export is delivered by CR-001-A's `export_audit` (tenant-scoped, reference-only).

**Boundary / hand-off to 001:** 002 owns *how long* (policy); 001 owns *how* (the durable tombstone/
cascade purge job and the production export endpoint). The retention scheduler/purge runner is 001's.

---

## CR-001-D — Platform security NFR

**001 (platform) must provide:** encryption at rest / in transit, vulnerability management, backup,
incident response — platform-wide non-functional requirements for future ISMAP / large-enterprise
security review (FR-MFG-025).

**002 (this layer) implements locally / minimally (Phase 9):**
- 002 does **not** implement these platform NFRs. `GovernanceService.governance_status` surfaces an
  `ismap_readiness_memo` that frames the work as **"ISMAP を見据えた設計"** and explicitly does **not**
  claim "registered" / "fully compliant" / "登録済み" (FR-MFG-026). The memo records the design intent;
  registration remains a separate process.

**Boundary / hand-off to 001:** entirely 001's responsibility; 002 only presents readiness posture and
must never overstate compliance.

---

## Deferred (out of Phase 9 scope)

- **T066 (PoC vertical slice)** is intentionally **not** implemented: it needs the US5 KPI surface
  (unbuilt). No KPI is stubbed. The closed `REQUIRED_EVENT_TYPES` audit taxonomy deliberately omits
  feedback/dashboard/KPI categories that depend on unbuilt US3/US5, so SC-MFG-010 is satisfiable within
  Phase-9 scope while still pinning the spec's audit-event list.
- Full DMS / e-signature / arbitrary version rollback remain non-goals (Solution-layer hard rules).
