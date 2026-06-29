"""P1-1 — wire the manufacturing safety overlay onto a DEPLOYED base system (GAP-F05).

``ManufacturingAnswerService`` is composed entirely from injected 001 services. ``ProductionSystem``
subclasses ``MvpSystem`` and exposes the SAME ``.retrieval`` / ``.gate`` / ``.answer_service`` /
``.registry`` / ``.llm``, so the safety overlay (high-risk classification, approved+effective evidence
gate, draft/obsolete never primary — incl. the GAP-S3 fix) runs over EITHER the in-memory MvpSystem
(Tier A) or the Postgres ProductionSystem (deployment) with no reimplementation.

The only deployment-specific piece is resolving ``ManufacturingDocumentMetadata`` from the PERSISTED
``Document.metadata`` (a dataclass in-memory, a jsonb dict from Postgres) instead of an in-process
dict — provided here, tombstone-aware (GAP-S2). Use ``build_manufacturing_answer_service(system)``
from the deployed answer-service to expose ``/internal/manufacturing/answer``.
"""

from __future__ import annotations

from datetime import date

from raku_rag.manufacturing.api.answer_ext import ManufacturingAnswerService
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY
from raku_rag.manufacturing.safety.classifier import (
    RuleHighRiskClassifier,
    semantic_danger_classifier_from_settings,
)


def registry_mfg_meta_resolver(system):
    """``get_mfg_meta(tenant_id, document_id)`` backed by the system's document registry.

    Reads the manufacturing metadata from the persisted ``Document.metadata`` — works for the
    in-memory dataclass form and the Postgres jsonb-dict form (via ``from_mapping``). Tombstone-aware:
    a source-deleted document resolves to ``None`` so deleted content cannot resurface (GAP-S2).
    """

    def get_mfg_meta(tenant_id: str, document_id: str) -> ManufacturingDocumentMetadata | None:
        doc = system.registry.get(tenant_id, document_id)
        if doc is None or getattr(doc, "tombstone", False):
            return None
        raw = doc.metadata.get(MFG_META_KEY)
        if raw is None:
            return None
        return ManufacturingDocumentMetadata.from_mapping(raw)

    return get_mfg_meta


def build_manufacturing_answer_service(
    system, *, today: date | None = None
) -> ManufacturingAnswerService:
    """Compose the manufacturing safety overlay over any 001 base system (MvpSystem/ProductionSystem)."""
    return ManufacturingAnswerService(
        retrieval=system.retrieval,
        groundedness=system.gate,
        answer_service=system.answer_service,
        get_mfg_meta=registry_mfg_meta_resolver(system),
        classifier=RuleHighRiskClassifier(
            llm=system.llm,
            semantic_classifier=semantic_danger_classifier_from_settings(
                system.settings, system.llm
            ),
        ),
        get_document=system.registry.get,
        today=today,
        visual_evidence_promotion=system.settings.visual_evidence_promotion,
    )


__all__ = ["build_manufacturing_answer_service", "registry_mfg_meta_resolver"]
