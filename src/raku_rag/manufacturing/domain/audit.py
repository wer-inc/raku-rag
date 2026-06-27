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

import hashlib
from dataclasses import dataclass, field, fields, replace
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


# --- T056: actor organizational context snapshot (FR-MFG-030) -----------------------------------
#
# ``factory_id`` / ``department_id`` are the US5 telemetry grouping axes. They are derived from the
# SAME FR-MFG-013 mapping as the ACL itself (NO new authz): department == the actor's 001 ACL group
# (falling back to a role when no group is present), factory == an explicit Factory context supplied
# by the caller (the actor's resolved territory). Snapshotting them onto the immutable AuditLogEntry
# at write time means later aggregation never has to re-resolve a mutable identity.


def actor_org_context(
    principal: IdentityClaims, *, factory_id: str | None = None
) -> tuple[str | None, str | None]:
    """Return ``(factory_id, department_id)`` for ``principal`` — the FR-MFG-013-derived org context.

    ``department_id`` is the actor's primary 001 ACL group (department IS a group, FR-MFG-013),
    falling back to the primary role if the actor carries no group. ``factory_id`` is the resolved
    Factory territory when the caller knows it (e.g. from a granted ManufacturingScope); otherwise
    ``None`` — never invented. Pure read-only derivation; builds no authorization.
    """
    department_id = (
        principal.groups[0]
        if principal.groups
        else (principal.roles[0] if principal.roles else None)
    )
    return (factory_id, department_id)


def stamp_org_context(
    entry: "AuditLogEntry", principal: IdentityClaims, *, factory_id: str | None = None
) -> "AuditLogEntry":
    """Return an immutable COPY of ``entry`` with the actor org-context snapshot applied (T056).

    Only fills ``factory_id`` / ``department_id`` (and ``actor_id`` if unset) so callers can stamp an
    already-built entry without mutating it — the snapshot is immutable once recorded.
    """
    fac, dept = actor_org_context(principal, factory_id=factory_id)
    return replace(
        entry,
        actor_id=entry.actor_id or principal.user_id,
        factory_id=entry.factory_id if entry.factory_id is not None else fac,
        department_id=entry.department_id if entry.department_id is not None else dept,
    )


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
    collection_id: str | None = (
        None  # answered collection (FR-MFG-030 collection axis); reference ID
    )

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


# --- T059: tamper-evidence (Base CR-001-A) -------------------------------------------------------
#
# Every stored entry carries a SHA-256 ``entry_hash`` over its canonical reference-only content,
# linked to the previous entry via ``prev_hash`` (per-tenant chain). The chain field is hashed too
# (so re-ordering also breaks it), but ``entry_hash`` itself is excluded from its own preimage.
# ``hashlib`` is stdlib — no new dependency. Mutating any stored field without re-hashing makes
# ``compute_entry_hash`` disagree with the stored ``entry_hash`` => ``verify_chain`` returns False.

_HASH_EXCLUDED_FIELDS: frozenset[str] = frozenset({"entry_hash"})


def _canonical(value) -> str:
    """Deterministic, dependency-free rendering of a field value for hashing."""
    if value is None:
        return "\x00"
    if isinstance(value, Enum):
        return f"E:{value.value}"
    if isinstance(value, bool):
        return f"B:{int(value)}"
    if isinstance(value, (tuple, list)):
        return "L:[" + ",".join(_canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted((str(k), _canonical(v)) for k, v in value.items())
        return "D:{" + ",".join(f"{k}={v}" for k, v in items) + "}"
    return f"S:{value}"


def compute_entry_hash(entry: "AuditLogEntry") -> str:
    """SHA-256 over the entry's canonical content (every field except ``entry_hash``).

    ``prev_hash`` is included so a re-link/re-order is also detected. Pure function of the entry's
    current field values — recomputing it over a mutated entry yields a different digest.
    """
    h = hashlib.sha256()
    for f in fields(entry):
        if f.name in _HASH_EXCLUDED_FIELDS:
            continue
        h.update(f.name.encode("utf-8"))
        h.update(b"\x1f")
        h.update(_canonical(getattr(entry, f.name)).encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


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
        """Persist a single audit entry. Free-text is redacted; reference IDs are kept verbatim.

        The entry is linked into the per-tenant SHA-256 hash chain at write time (Base CR-001-A):
        ``prev_hash`` = the previous entry's ``entry_hash`` (None for the first entry), and
        ``entry_hash`` is computed over the stored (already-redacted) content. These fields are
        additive and default-safe; the reference-IDs-only / redaction / tenant-isolation guarantees
        are unchanged.
        """
        if not entry.tenant_id:
            raise TenantIsolationError("resource not found")  # untenanted entry is rejected
        safe = self._redact_entry(entry)
        chain = self._by_tenant.setdefault(safe.tenant_id, [])
        safe.prev_hash = chain[-1].entry_hash if chain else None
        safe.entry_hash = compute_entry_hash(safe)
        chain.append(safe)

    def _redact_entry(self, entry: AuditLogEntry) -> AuditLogEntry:
        return sanitize_audit_log_entry(entry, self._redactor)

    # --- read (tenant-scoped; single source of truth for telemetry/KPI) ----------------------
    def read_all(self, principal: IdentityClaims) -> tuple[AuditLogEntry, ...]:
        """Return every entry for the principal's own tenant. Cross-tenant access is impossible.

        Entries are scoped strictly by the principal's ``tenant_id``; another tenant's records are
        never returned (and their existence is never disclosed).
        """
        return tuple(self._by_tenant.get(principal.tenant_id, ()))

    def read_for_tenant(
        self, principal: IdentityClaims, tenant_id: str
    ) -> tuple[AuditLogEntry, ...]:
        """Read entries for ``tenant_id``; raises if it is not the principal's tenant.

        Telemetry/KPI aggregation calls this so any cross-tenant aggregation request fails closed.
        """
        enforce_same_tenant(principal, resource_tenant_id=tenant_id)
        return tuple(self._by_tenant.get(tenant_id, ()))

    # --- tamper-evidence verification (Base CR-001-A) ----------------------------------------
    def verify_chain(self, principal: IdentityClaims) -> bool:
        """Return True iff the principal's tenant log is an intact SHA-256 hash chain.

        Each entry's ``prev_hash`` must equal the previous entry's stored ``entry_hash`` and each
        stored ``entry_hash`` must recompute from the entry's current content. A mutated entry
        (its content changed without re-hashing) makes the recomputation disagree => False.
        """
        prev: str | None = None
        for entry in self._by_tenant.get(principal.tenant_id, ()):
            if entry.prev_hash != prev:
                return False
            if entry.entry_hash != compute_entry_hash(entry):
                return False
            prev = entry.entry_hash
        return True


def sanitize_audit_log_entry(
    entry: AuditLogEntry, redactor: Redactor | None = None
) -> AuditLogEntry:
    """Return a redacted copy suitable for durable audit storage."""
    redactor = redactor or Redactor()
    red = redactor.redact
    text_patch = {
        name: red(value)
        for name in _REDACT_TEXT_FIELDS
        if isinstance((value := getattr(entry, name)), str)
    }
    safe_metadata = {
        k: _redact_metadata_value(v, red) for k, v in entry.client_metadata.items()
    }
    return replace(entry, client_metadata=safe_metadata, **text_patch)


def _redact_metadata_value(value, redact):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(k): _redact_metadata_value(v, redact) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_metadata_value(v, redact) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_metadata_value(v, redact) for v in value)
    return value
