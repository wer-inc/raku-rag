"""T062/T063/T064 — Governance / DataUsePolicy / audit-export API surface (contracts §F/§G).

In-memory analog of three governance endpoints, exposed as Python methods on ``GovernanceService``
and surfaced on ``ManufacturingSystem``. Mirrors contracts/mfg-openapi.md §F:

  - GET  /v1/manufacturing/policy/data-use         -> get_data_use_policy(tenant_id)        (T062)
  - PUT  /v1/manufacturing/policy/data-use (admin) -> update_data_use_policy(...)           (T062)
  - GET  /v1/manufacturing/governance/status       -> governance_status(tenant_id)          (T063)
  - GET  /v1/manufacturing/audit/export (admin)    -> export_audit(...)                     (T064)

Reuses the configured ``DataUsePolicyStore`` (per-tenant, opt-in invariant, version bump) and
the shared ``AuditLogWriter`` (reference-IDs-only, redacted, hash-chained, tenant-scoped).
A DataUsePolicy change is recorded to the audit log (FR-MFG-019). Audit export is tenant-scoped and
reference-only (the 001 Redactor already ran at write time; export re-applies it as defence-in-depth).

stdlib only.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
from datetime import datetime, timezone
from enum import Enum

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import AuditLogEntry
from raku_rag.manufacturing.domain.policy import DataUsePolicy
from raku_rag.manufacturing.interfaces import AuditLogWriter, DataUsePolicyStore
from raku_rag.observability.redaction import Redactor

# FR-MFG-025/026: the readiness memo is "designed-with-ISMAP-in-view", NOT a registration/compliance
# claim. It MUST NOT assert "registered" / "fully compliant" / "登録済み".
ISMAP_READINESS_MEMO = (
    "ISMAPの管理策を見据えた設計（no-train・監査証跡・安全ゲート・ドラフトレビュー・"
    "グラウンデッドネスを実装）。本機能はISMAP登録・準拠を主張するものではなく、"
    "登録は別途の手続きを要する。"
)

# Patch keys that name a no-train / retention / opt-in change (for the audit action label, FR-MFG-019).
_NO_TRAIN_PATCH_KEYS = frozenset(
    {
        "no_train_default",
        "training_opt_in",
        "opt_in_contract_ref",
        "provider_no_train_required",
        "no_train_fallback",
    }
)
_RETENTION_PATCH_KEYS = frozenset({"retention_customer", "retention_audit"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _policy_action(patch: dict) -> str:
    """Label the policy change for the audit log so coverage predicates can match it (FR-MFG-021)."""
    keys = set(patch)
    if keys & _NO_TRAIN_PATCH_KEYS:
        return "policy.no_train.change"
    if keys & _RETENTION_PATCH_KEYS:
        return "policy.retention.change"
    return "policy.setting.change"


def _entry_to_dict(entry: AuditLogEntry, redactor: Redactor) -> dict:
    """Reference-only serialization of a stored entry. Enums -> values; tuples -> lists.

    Free-text fields are already redacted at write time; re-applying the 001 ``Redactor`` here is
    defence-in-depth for the export boundary (FR-MFG-023). Reference-ID / hash fields are left
    verbatim so a downstream importer can re-verify the chain.
    """
    _verbatim = {
        "resource_id",
        "citation_ids",
        "document_ids_used",
        "prev_hash",
        "entry_hash",
        "log_id",
        "request_id",
        "trace_id",
        "tenant_id",
        "actor_id",
    }
    out: dict = {}
    for f in dataclasses.fields(entry):
        value = getattr(entry, f.name)
        if isinstance(value, Enum):
            value = value.value
        elif isinstance(value, tuple):
            value = list(value)
        elif isinstance(value, dict):
            value = {k: (redactor.redact(v) if isinstance(v, str) else v) for k, v in value.items()}
        elif isinstance(value, str) and f.name not in _verbatim:
            value = redactor.redact(value)
        out[f.name] = value
    return out


class GovernanceService:
    """Governance facade over the reused policy store + audit writer (T062/T063/T064)."""

    def __init__(
        self,
        *,
        policy_store: DataUsePolicyStore,
        audit: AuditLogWriter,
        redactor: Redactor | None = None,
    ) -> None:
        self._store = policy_store
        self._audit = audit
        self._redactor = redactor or Redactor()

    # --- GET /v1/manufacturing/policy/data-use (T062) ----------------------------------------------
    def get_data_use_policy(self, tenant_id: str) -> DataUsePolicy:
        """Return the tenant policy, auto-seeding the GQ1/GQ2 safe default with a policy_version."""
        return self._store.get(tenant_id)

    # --- PUT /v1/manufacturing/policy/data-use (T062) ----------------------------------------------
    def update_data_use_policy(
        self, *, tenant_id: str, patch: dict, actor: IdentityClaims
    ) -> DataUsePolicy:
        """Apply a patch (opt-in invariant enforced, version bumped) and audit the change (FR-MFG-019).

        ``training_opt_in=True`` without a non-empty ``opt_in_contract_ref`` raises ``ValueError`` and
        the stored policy is left unchanged (the store validates before persisting). On success the
        change is recorded to the audit log with reference IDs only — never the contract body / PII.
        """
        updated = self._store.update(tenant_id, patch, actor)  # raises on invalid opt-in
        self._audit_policy_change(tenant_id=tenant_id, patch=patch, policy=updated, actor=actor)
        return updated

    def _audit_policy_change(
        self, *, tenant_id: str, patch: dict, policy: DataUsePolicy, actor: IdentityClaims
    ) -> None:
        action = _policy_action(patch)
        ts = _now()
        # Reference-only: record WHICH settings changed (key names), never the contract ref value.
        changed_keys = ",".join(sorted(patch))
        self._audit.record(
            AuditLogEntry(
                tenant_id=tenant_id,
                log_id=f"{action}:{tenant_id}:{ts}",
                timestamp=ts,
                actor_id=actor.user_id if actor else None,
                actor_role=(",".join(actor.roles) if actor and actor.roles else None),
                action=action,
                resource_type="data_use_policy",
                resource_id=tenant_id,  # reference ID only
                decision="updated",
                reason=changed_keys,  # setting NAMES only — no values
                policy_version=policy.policy_version,
            )
        )

    # --- GET /v1/manufacturing/governance/status (T063) --------------------------------------------
    def governance_status(self, tenant_id: str) -> dict:
        """Present the AI-governance core features + an ISMAP readiness memo (FR-MFG-024~026)."""
        policy = self._store.get(tenant_id)
        return {
            "tenant_id": tenant_id,
            "policy_version": policy.policy_version,
            "no_train": {
                "no_train_default": policy.no_train_default,
                "training_opt_in": policy.training_opt_in,
                "provider_no_train_required": policy.provider_no_train_required,
                "no_train_fallback": policy.no_train_fallback.value,
            },
            "audit_coverage": {
                "tamper_evident": True,
                "reference_ids_only": True,
            },
            "safety_gate": {"enabled": True, "high_risk_requires_approved_citation": True},
            "draft_review": {
                "ai_output_always_draft": True,
                "reviewer_required_for_approval": True,
            },
            "groundedness": {"enabled": True, "citation_required": True},
            "retention": {
                "retention_customer_days": policy.retention_customer,
                "retention_audit_days": policy.retention_audit,
            },
            "ismap_readiness_memo": ISMAP_READINESS_MEMO,
        }

    # --- GET /v1/manufacturing/audit/export (T064) -------------------------------------------------
    def export_audit(self, *, principal: IdentityClaims, fmt: str = "jsonl"):
        """Export the principal's OWN tenant's audit entries (tenant-scoped, reference-only).

        fmt in {"jsonl", "csv", "dict"}. Entries expose reference IDs + the prev_hash/entry_hash chain
        so a downstream importer can re-verify tamper-evidence. Cross-tenant references are impossible
        (the writer's ``read_all`` is tenant-scoped to the principal). Admin export is itself audited.
        """
        entries = self._audit.read_all(principal)
        records = [_entry_to_dict(e, self._redactor) for e in entries]
        self._audit_export(principal, fmt=fmt, count=len(records))

        if fmt == "dict":
            return records
        if fmt == "jsonl":
            return "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records)
        if fmt == "csv":
            if not records:
                return ""
            cols = list(records[0].keys())
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                writer.writerow({k: _csv_cell(r.get(k)) for k in cols})
            return buf.getvalue()
        raise ValueError(f"unsupported export format: {fmt!r}")

    def _audit_export(self, principal: IdentityClaims, *, fmt: str, count: int) -> None:
        """Audit an admin audit-export (a governance/admin setting access; FR-MFG-021)."""
        ts = _now()
        self._audit.record(
            AuditLogEntry(
                tenant_id=principal.tenant_id,
                log_id=f"audit.export:{principal.tenant_id}:{ts}",
                timestamp=ts,
                actor_id=principal.user_id,
                action="audit.export",
                resource_type="audit_log",
                resource_id=principal.tenant_id,  # reference ID only
                decision=fmt,
                reason=f"records={count}",
            )
        )


def _csv_cell(value) -> str:
    """Render a value as a single CSV cell (lists/dicts -> compact JSON; None -> '')."""
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)
