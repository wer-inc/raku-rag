"""T028 — ApprovalWorkflow: lightweight approval lifecycle + imported-approval source of truth.

Two responsibilities (FR-MFG-004 / FR-MFG-004a):

  (1) A LIGHTWEIGHT workflow draft -> pending_review -> approved -> obsolete. A
      ``transition(to_status)`` updates the document's ``ManufacturingDocumentMetadata`` (the same
      record read by the reused 001 search/answer path) and sets ``approval_source = workflow``.

  (2) ``import_external(...)`` imports an upstream approval as the SOURCE OF TRUTH: it sets
      ``approval_source = imported`` and OVERRIDES whatever state the lightweight workflow had reached
      (e.g. an imported APPROVED+effective approval wins even after the local workflow marked the doc
      OBSOLETE). FR-MFG-004a.

EVERY transition AND every external import is recorded to the Phase-2 ``AuditLogWriter`` with
reference IDs only (no body text) — FR-MFG-021.

This layer does NOT reimplement search/deletion/tenancy. It mutates the manufacturing metadata that
the 001 path already reads, and re-propagates it onto the indexed chunks via the MetadataEnricher.

stdlib only. Structurally satisfies ``raku_rag.manufacturing.interfaces.ApprovalWorkflow``.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Callable

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import AuditLogEntry, InMemoryAuditLogWriter
from raku_rag.manufacturing.domain.metadata import (
    ApprovalSource,
    ApprovalStatus,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.ingestion.metadata_enrichment import MetadataEnricher
from raku_rag.manufacturing.interfaces import ApprovalState

GetMeta = Callable[[str, str], ManufacturingDocumentMetadata | None]
SetMeta = Callable[[str, str, ManufacturingDocumentMetadata], None]

# Permissive lightweight forward lifecycle. Any of these target states is accepted by transition().
_WORKFLOW_STATES: tuple[str, ...] = tuple(s.value for s in ApprovalStatus)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalWorkflow:
    """Lightweight approval workflow + external-approval import (audited)."""

    def __init__(
        self,
        *,
        get_meta: GetMeta,
        set_meta: SetMeta,
        audit: InMemoryAuditLogWriter,
        enricher: MetadataEnricher,
    ) -> None:
        self._get_meta = get_meta
        self._set_meta = set_meta
        self._audit = audit
        self._enricher = enricher

    # --- (1) lightweight workflow ----------------------------------------------------------------
    def transition(
        self, tenant_id: str, document_id: str, to_status: str, actor: IdentityClaims
    ) -> ApprovalState:
        """Drive the lightweight workflow to ``to_status``; approval_source = workflow. Audited."""
        status = self._coerce_status(to_status)
        meta = self._require_meta(tenant_id, document_id)

        approved_by = actor.user_id if status == ApprovalStatus.APPROVED else meta.approved_by
        approved_at = _now() if status == ApprovalStatus.APPROVED else meta.approved_at
        obsolete_at = _now() if status == ApprovalStatus.OBSOLETE else meta.obsolete_at

        updated = dataclasses.replace(
            meta,
            approval_status=status,
            approval_source=ApprovalSource.WORKFLOW,
            approved_by=approved_by,
            approved_at=approved_at,
            obsolete_at=obsolete_at,
        )
        self._persist(tenant_id, document_id, updated)
        self._audit_transition(
            tenant_id, document_id, action="approval.transition", status=updated, actor=actor
        )
        return self._to_state(updated)

    # --- (2) imported approval = source of truth -------------------------------------------------
    def import_external(
        self,
        tenant_id: str,
        document_id: str,
        external: dict,
        actor: IdentityClaims | None = None,
    ) -> ApprovalState:
        """Import an upstream approval as SOURCE OF TRUTH; overrides workflow state. Audited."""
        meta = self._require_meta(tenant_id, document_id)
        status = self._coerce_status(external.get("approval_status", ApprovalStatus.APPROVED.value))
        updated = dataclasses.replace(
            meta,
            approval_status=status,
            approval_source=ApprovalSource.IMPORTED,  # imported overrides the workflow (FR-MFG-004a)
            effective_date=external.get("effective_date", meta.effective_date),
            approved_by=external.get("approved_by", meta.approved_by),
            approved_at=external.get("approved_at", meta.approved_at or _now()),
        )
        self._persist(tenant_id, document_id, updated)
        self._audit_transition(
            tenant_id, document_id, action="approval.import_external", status=updated, actor=actor
        )
        return self._to_state(updated)

    # --- helpers ---------------------------------------------------------------------------------
    def _coerce_status(self, to_status: str) -> ApprovalStatus:
        value = to_status.value if isinstance(to_status, ApprovalStatus) else str(to_status)
        if value not in _WORKFLOW_STATES:
            raise ValueError(f"unknown approval status: {to_status!r}")
        return ApprovalStatus(value)

    def _require_meta(self, tenant_id: str, document_id: str) -> ManufacturingDocumentMetadata:
        meta = self._get_meta(tenant_id, document_id)
        if meta is None:
            # No prior metadata: seed a draft so a transition/import can still attach.
            meta = ManufacturingDocumentMetadata(
                tenant_id=tenant_id,
                document_id=document_id,
                approval_status=ApprovalStatus.DRAFT,
            )
        return meta

    def _persist(
        self, tenant_id: str, document_id: str, meta: ManufacturingDocumentMetadata
    ) -> None:
        self._set_meta(tenant_id, document_id, meta)
        # Re-decorate the Document + indexed Chunks so search/answer read the new approval state.
        self._enricher.attach(tenant_id, document_id, meta)

    def _to_state(self, meta: ManufacturingDocumentMetadata) -> ApprovalState:
        return ApprovalState(
            tenant_id=meta.tenant_id,
            document_id=meta.document_id,
            approval_status=meta.approval_status.value,
            approval_source=meta.approval_source.value,
            effective_date=meta.effective_date,
            approved_by=meta.approved_by,
            approved_at=meta.approved_at,
        )

    def _audit_transition(
        self,
        tenant_id: str,
        document_id: str,
        *,
        action: str,
        status: ManufacturingDocumentMetadata,
        actor: IdentityClaims | None,
    ) -> None:
        ts = _now()
        self._audit.record(
            AuditLogEntry(
                tenant_id=tenant_id,
                log_id=f"{action}:{document_id}:{ts}",
                timestamp=ts,
                actor_id=actor.user_id if actor else None,
                actor_role=(",".join(actor.roles) if actor and actor.roles else None),
                action=action,
                resource_type="document",
                resource_id=document_id,  # reference ID only — never body text
                decision=status.approval_status.value,
                reason=status.approval_source.value,
                approval_status_at_use=status.approval_status.value,
                document_ids_used=(document_id,),
            )
        )
