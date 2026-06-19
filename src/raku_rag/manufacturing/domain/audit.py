"""T006 — AuditLogEntry + SafetyTelemetryResult (data-model §H/§I, FR-MFG-021~023/030).

Tenant-scoped, tamper-evident structured audit record; the SINGLE SOURCE OF TRUTH telemetry/KPI are
derived from. Extends the 001 base AuditLog (Base CR-001-A) into the product layer.

Hard rules reflected in the schema (enforced by stage-2 AuditLogWriter + the safety hard gate):
- REFERENCE IDs ONLY — never store PII / secrets / confidential body text (SC-MFG-010 = 0).
  001 Redactor (raku_rag.observability.redaction) is reused at write time.
- Cross-tenant references forbidden (reuse 001 tenancy).
- hash chain: prev_hash / entry_hash provide tamper-evidence (Base CR-001-A).
- Telemetry is DERIVED from these entries; no double counting (FR-MFG-030).

Schema + enums only — no hashing / writing / aggregation behaviour (stage-2).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from raku_rag.core.errors import TenantIsolationError
from raku_rag.core.tenancy import enforce_same_tenant
from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.safety import SafetyBlockReason
from raku_rag.observability.redaction import Redactor


class TelemetryAxis(str, Enum):
    """SafetyTelemetry.aggregate axis (contracts §8). ``tenant`` is the implicit scope."""

    COLLECTION = "collection"
    FACTORY = "factory"
    DEPARTMENT = "department"


@dataclass
class AuditLogEntry:
    """Structured audit record (data-model §H). Only reference IDs — no PII/secret/body text."""

    tenant_id: str
    log_id: str
    timestamp: str  # ISO timestamp

    # correlation
    request_id: str | None = None
    trace_id: str | None = None

    # actor
    actor_id: str | None = None
    actor_role: str | None = None
    actor_group: str | None = None
    app_id: str | None = None
    api_client_id: str | None = None
    source_ip: str | None = None
    client_metadata: dict = field(default_factory=dict)  # only non-PII, redaction applied

    # actor organizational context for aggregation (FR-MFG-030)
    factory_id: str | None = None  # from Factory
    department_id: str | None = None  # from base ACL group/role

    # action
    action: str = ""
    resource_type: str | None = None
    resource_id: str | None = None
    decision: str | None = None
    reason: str | None = None
    policy_version: str | None = None

    # safety / approval snapshot
    high_risk_classification_result: bool | None = None
    safety_block_reason: SafetyBlockReason | None = None
    approval_status_at_use: str | None = None  # ApprovalStatus value

    # evidence references (REFERENCE IDs ONLY)
    citation_ids: tuple[str, ...] = ()
    document_ids_used: tuple[str, ...] = ()

    # integrity (hash chain; Base CR-001-A)
    prev_hash: str | None = None
    entry_hash: str | None = None


@dataclass(frozen=True)
class SafetyTelemetryResult:
    """Derived safety telemetry view (data-model §I, FR-MFG-030).

    ``block_breakdown`` is mutually exclusive by SafetyBlockReason and sums to
    ``safety_gate_block_count``; aggregated from AuditLogEntry (no double counting).
    """

    tenant_id: str
    axis: TelemetryAxis | None = None
    axis_value: str | None = None  # e.g. a specific factory_id / department_id / collection_id
    time_range: tuple[str, str] | None = None  # (start_iso, end_iso)
    high_risk_query_count: int = 0
    safety_gate_block_count: int = 0
    block_breakdown: dict = field(default_factory=dict)  # {SafetyBlockReason.value: count}


# Free-text fields that may incidentally carry PII / secrets / body text and therefore MUST be
# passed through the 001 Redactor before the entry is durably stored (SC-MFG-010 = PII 0).
# Reference-ID fields (citation_ids, document_ids_used, *_id, hashes) are NOT redacted — they are
# opaque identifiers and redaction would corrupt the audit chain.
_REDACT_TEXT_FIELDS: tuple[str, ...] = (
    "action",
    "reason",
    "decision",
    "source_ip",
    "actor_role",
    "actor_group",
)


class InMemoryAuditLogWriter:
    """T009 — In-memory, tenant-scoped AuditLogWriter (FR-MFG-021/022/023, SC-MFG-010).

    Single source of truth for safety telemetry / KPI: every recorded event lands here and
    aggregation reads exclusively from it (no parallel store, no double counting).

    Hard guarantees:
    - REFERENCE IDs ONLY. The schema already carries only reference IDs; as defence-in-depth this
      writer additionally runs every free-text field (and every string value inside
      ``client_metadata``) through the reused 001 ``Redactor`` so an accidental PII/secret/body
      leak is masked before storage (SC-MFG-010 = PII 混入 0).
    - Tenant isolation. Reads are bound to a single tenant via the reused
      ``raku_rag.core.tenancy.enforce_same_tenant``; a cross-tenant read raises
      ``TenantIsolationError`` and never discloses another tenant's data or its existence.

    Concrete; structurally satisfies the ``raku_rag.manufacturing.interfaces.AuditLogWriter`` ABC
    (matching ``record(entry)`` signature). It is deliberately NOT a top-level subclass: interfaces
    imports this module, so subclassing would create an import cycle.
    """

    def __init__(self, redactor: Redactor | None = None) -> None:
        self._redactor = redactor or Redactor()
        # tenant_id -> append-only list of stored (already-redacted) entries.
        self._by_tenant: dict[str, list[AuditLogEntry]] = {}

    # --- write -------------------------------------------------------------------------------
    def record(self, entry: AuditLogEntry) -> None:
        """Persist a single audit entry. Free-text is redacted; reference IDs are kept verbatim."""
        if not entry.tenant_id:
            raise TenantIsolationError("resource not found")  # untenanted entry is rejected
        safe = self._redact_entry(entry)
        self._by_tenant.setdefault(safe.tenant_id, []).append(safe)

    def _redact_entry(self, entry: AuditLogEntry) -> AuditLogEntry:
        red = self._redactor.redact
        text_patch = {
            name: red(value)
            for name in _REDACT_TEXT_FIELDS
            if isinstance((value := getattr(entry, name)), str)
        }
        safe_metadata = {
            k: (red(v) if isinstance(v, str) else v) for k, v in entry.client_metadata.items()
        }
        # ``replace`` yields a copy so the caller's object is never mutated in place.
        return replace(entry, client_metadata=safe_metadata, **text_patch)

    # --- read (tenant-scoped; single source of truth for telemetry/KPI) ----------------------
    def read_all(self, principal: IdentityClaims) -> tuple[AuditLogEntry, ...]:
        """Return every entry for the principal's own tenant. Cross-tenant access is impossible.

        Entries are scoped strictly by the principal's ``tenant_id``; another tenant's records are
        never returned (and their existence is never disclosed).
        """
        return tuple(self._by_tenant.get(principal.tenant_id, ()))

    def read_for_tenant(self, principal: IdentityClaims, tenant_id: str) -> tuple[AuditLogEntry, ...]:
        """Read entries for ``tenant_id``; raises if it is not the principal's tenant.

        Telemetry/KPI aggregation calls this so any cross-tenant aggregation request fails closed.
        """
        enforce_same_tenant(principal, resource_tenant_id=tenant_id)
        return tuple(self._by_tenant.get(tenant_id, ()))
