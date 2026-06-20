"""US1 manufacturing test helpers (TDD, Phase 3).

Mirrors tests/helpers.py for the 001 MVP core, but assembles the manufacturing SOLUTION LAYER:
the SafetyGate overlay that sits AFTER the 001 GroundednessGate on the reused answer path.

The entrypoint asserted here — ``raku_rag.manufacturing.app.ManufacturingSystem`` — is the stage-2
composition root (analog of ``raku_rag.app.MvpSystem``). It does NOT exist yet, so importing it FAILS
now (RED for missing impl, NOT an unrelated import error). Stage-2 builds it by WRAPPING the existing
``MvpSystem`` (RetrievalService / AnswerService / GroundednessGate / AclPolicy / tenancy are reused,
not reimplemented) and layering the manufacturing ``HighRiskClassifier`` + ``SafetyGate``.

Contract the stage-2 entrypoint must satisfy (spec FR-MFG-005/006/007/015/030, contracts §A/§4,
quickstart S2/S3/S4, data-model §B/§E):

``ManufacturingSystem()``
  - ``.grant(tenant_id, scope_type, scope_id, subject_type, subject_id)`` — delegates to 001 AclPolicy.
  - ``.ingest_manufacturing(*, tenant_id, collection_id, document_id, text, metadata, source_id="src")``
      ingests the body via the 001 ingestion path AND attaches ``ManufacturingDocumentMetadata`` to the
      001 Document.metadata (read later by HighRiskClassifier + SafetyGate).
  - ``.answer(principal, query, collection_id=None, intent_hint=None) -> ManufacturingAnswer``
      runs the 001 answer path then the safety overlay.

``ManufacturingAnswer`` carries the base 001 ``Answer`` fields (``status``, ``text``, ``citations``,
``used_chunks``, ``freshness`` ...) PLUS the manufacturing extension (contracts §A):
  - ``high_risk: bool``
  - ``high_risk_reason_codes: tuple[str, ...]``
  - ``safety_block_reason: str | None``        (one normalized SafetyBlockReason value or None)
  - ``obsolete_warning: bool``
  - ``requires_onsite_confirmation: bool``
and each citation exposes ``approval_status`` / ``effective_date`` / ``approval_source`` (FR-MFG-004).
"""

from __future__ import annotations

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.metadata import (
    ApprovalSource,
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)

T = "tenant_mfg"


def fresh() -> ManufacturingSystem:
    return ManufacturingSystem()


def claims(tenant: str, user: str, groups=(), roles=()) -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, groups=tuple(groups), roles=tuple(roles))


def mfg_meta(
    *,
    tenant_id: str,
    document_id: str,
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
    effective_date: str | None = "2026-01-10",
    approval_source: ApprovalSource = ApprovalSource.IMPORTED,
    document_kind: DocumentKind | None = None,
    safety_category: str | None = None,
    quality_category: str | None = None,
    equipment_operation_category: str | None = None,
    hazard_tags: tuple[str, ...] = (),
    process_id: str | None = None,
    equipment_id: str | None = None,
    obsolete_at: str | None = None,
    superseded_by: str | None = None,
    customer: str | None = None,
    defect_type: str | None = None,
) -> ManufacturingDocumentMetadata:
    """Build a ManufacturingDocumentMetadata; APPROVED + effective by default (the safe baseline)."""
    return ManufacturingDocumentMetadata(
        tenant_id=tenant_id,
        document_id=document_id,
        approval_status=approval_status,
        effective_date=effective_date,
        approval_source=approval_source,
        document_kind=document_kind,
        safety_category=safety_category,
        quality_category=quality_category,
        equipment_operation_category=equipment_operation_category,
        hazard_tags=hazard_tags,
        process_id=process_id,
        equipment_id=equipment_id,
        obsolete_at=obsolete_at,
        superseded_by=superseded_by,
        customer=customer,
        defect_type=defect_type,
    )
