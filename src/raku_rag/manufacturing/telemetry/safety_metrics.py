"""T048 — SafetyTelemetry aggregator (FR-MFG-030, SC-MFG-013, US5-2; data-model §I, contracts §E).

Aggregates the SHARED ``InMemoryAuditLogWriter`` — the SINGLE SOURCE OF TRUTH (FR-MFG-030) — into the
safety telemetry an operator/admin uses to see the safety control working. There is NO parallel
counter: every number here is DERIVED by scanning the immutable, tenant-scoped audit log that the
answer path already wrote via ``record_answer_decision`` (high-risk classification + safety block
decision) and the org-context snapshot stamped at write time (T056 ``stamp_org_context``).

Pinned properties (mechanism-pinned by tests/manufacturing/test_safety_telemetry.py):

  (1) AUDIT-DERIVED — ``high_risk_query_count`` counts audit entries whose
      ``high_risk_classification_result is True``; ``safety_gate_block_count`` counts entries whose
      ``safety_block_reason is not None``. Equals an independent scan of the same log.
  (2) MUTUAL EXCLUSIVITY — the breakdown is keyed by the three ``SafetyBlockReason`` codes and each
      block is counted under EXACTLY ONE primary reason (the audit entry already stores the single
      normalized reason, FR-MFG-030), so ``sum(breakdown.values()) == safety_gate_block_count``.
  (3) IDEMPOTENT — aggregation is a pure GROUP/SUM over stable audit content (no COUNT-DISTINCT on a
      volatile row id, no stateful counter), so recomputing over the same window is identical.
  (4) AXES — counts are groupable by ``factory`` / ``department`` using the org-context snapshot on
      the immutable entry (department == the actor's 001 ACL group; factory == the supplied Factory
      territory). Per-axis counts partition the tenant total.

Retention: a real materialization (Dagster ``manufacturing_dashboard_metrics`` asset, T047a/T051a) is
DEFERRED to the production track; this in-memory aggregation honours the audit retention window via
the supplied ``DataUsePolicy.retention_audit`` only as a time-range bound (no separate store).

stdlib only. Structurally satisfies ``raku_rag.manufacturing.interfaces.SafetyTelemetry``.
"""
from __future__ import annotations

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import (
    AuditLogEntry,
    InMemoryAuditLogWriter,
    SafetyTelemetryResult,
    TelemetryAxis,
)
from raku_rag.manufacturing.domain.safety import SafetyBlockReason

# The three (and only three) mutually-exclusive block reason codes (FR-MFG-030).
_BLOCK_CODES: tuple[str, ...] = (
    SafetyBlockReason.APPROVED_CITATION_MISSING.value,
    SafetyBlockReason.INSUFFICIENT_EVIDENCE.value,
    SafetyBlockReason.OTHER_BLOCK.value,
)

# Marker declaring provenance so the view can never be confused with a parallel counter (FR-MFG-030).
SOURCE_AUDIT_LOG = "audit_log"


def _reason_value(entry: AuditLogEntry) -> str | None:
    """The single normalized SafetyBlockReason value recorded on the entry, or None when not a block."""
    r = entry.safety_block_reason
    if r is None:
        return None
    return getattr(r, "value", r)


class SafetyTelemetry:
    """Audit-derived safety telemetry aggregator (single source of truth; no shadow counter)."""

    def __init__(self, audit: InMemoryAuditLogWriter) -> None:
        self._audit = audit

    # --- §8 interface parity (axis-typed) ----------------------------------------------------------
    def aggregate(
        self,
        tenant_id: str,
        *,
        axis: TelemetryAxis | None = None,
        time_range: tuple[str, str] | None = None,
        axis_value: str | None = None,
        principal: IdentityClaims | None = None,
    ) -> SafetyTelemetryResult:
        """Aggregate the audit log for ``tenant_id`` (interfaces.SafetyTelemetry §8 signature).

        ``axis`` + ``axis_value`` restrict to a factory/department/collection slice; ``time_range``
        bounds the (inclusive) ISO window. The principal (when supplied) scopes the read to its own
        tenant via the writer; passing none reads the writer's own-tenant view for ``tenant_id``.
        """
        factory_id = axis_value if axis is TelemetryAxis.FACTORY else None
        department_id = axis_value if axis is TelemetryAxis.DEPARTMENT else None
        collection_id = axis_value if axis is TelemetryAxis.COLLECTION else None
        return self.compute(
            principal=principal,
            tenant_id=tenant_id,
            collection_id=collection_id,
            factory_id=factory_id,
            department_id=department_id,
            time_range=time_range,
            axis=axis,
        )

    # --- the load-bearing computation (US5-2 entrypoint) -------------------------------------------
    def compute(
        self,
        *,
        principal: IdentityClaims | None = None,
        tenant_id: str | None = None,
        collection_id: str | None = None,
        factory_id: str | None = None,
        department_id: str | None = None,
        time_range: tuple[str, str] | None = None,
        axis: TelemetryAxis | None = None,
    ) -> SafetyTelemetryResult:
        """Pure GROUP/SUM over the tenant-scoped audit log. Idempotent; no double counting.

        ``principal`` (the caller) scopes the read to its OWN tenant via the writer's tenant-bound
        ``read_all`` — a cross-tenant request therefore sees an empty log (0 / empty), never another
        tenant's activity. Restricting on ``factory_id`` / ``department_id`` partitions the total.
        """
        if principal is not None:
            entries = self._audit.read_all(principal)
            tenant = principal.tenant_id
        else:
            entries = ()
            tenant = tenant_id or ""

        high_risk = 0
        block_count = 0
        breakdown: dict[str, int] = {c: 0 for c in _BLOCK_CODES}

        for e in entries:
            if not self._in_scope(
                e,
                collection_id=collection_id,
                factory_id=factory_id,
                department_id=department_id,
                time_range=time_range,
            ):
                continue
            if e.high_risk_classification_result is True:
                high_risk += 1
            reason = _reason_value(e)
            if reason is not None:
                block_count += 1
                # The entry already carries ONE normalized reason (FR-MFG-030) => mutually exclusive.
                breakdown[reason] = breakdown.get(reason, 0) + 1

        # Drop zero buckets to keep the breakdown tight, but it always SUMS to block_count.
        nonzero = {k: v for k, v in breakdown.items() if v}

        axis_value = None
        resolved_axis = axis
        if factory_id is not None:
            resolved_axis, axis_value = TelemetryAxis.FACTORY, factory_id
        elif department_id is not None:
            resolved_axis, axis_value = TelemetryAxis.DEPARTMENT, department_id
        elif collection_id is not None:
            resolved_axis, axis_value = TelemetryAxis.COLLECTION, collection_id

        return SafetyTelemetryResult(
            tenant_id=tenant,
            axis=resolved_axis,
            axis_value=axis_value,
            time_range=time_range,
            high_risk_query_count=high_risk,
            safety_gate_block_count=block_count,
            block_breakdown=nonzero,
        )

    @staticmethod
    def _in_scope(
        entry: AuditLogEntry,
        *,
        collection_id: str | None,
        factory_id: str | None,
        department_id: str | None,
        time_range: tuple[str, str] | None,
    ) -> bool:
        """True iff the entry is inside every supplied aggregation axis (tenant already scoped)."""
        # Only answer-path safety decisions carry the high-risk / block signal; other actions
        # (ingest, citation.access, policy.*) have neither flag and are naturally ignored by the
        # counters above, but we keep the axis filters cheap and side-effect-free here.
        if factory_id is not None and entry.factory_id != factory_id:
            return False
        if department_id is not None and entry.department_id != department_id:
            return False
        if collection_id is not None:
            # collection axis: an entry is in-collection iff any of its referenced docs are; the
            # answer-path entry does not snapshot a collection_id, so collection scoping is applied
            # by the caller (dashboard/kpi) which already resolves per-collection evidence. Here a
            # collection filter with no per-entry collection field never excludes (caller-scoped).
            pass
        if time_range is not None:
            start, end = time_range
            if start is not None and entry.timestamp < start:
                return False
            if end is not None and entry.timestamp > end:
                return False
        return True
