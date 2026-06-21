"""P1-1 — the manufacturing safety overlay runs over a DEPLOYED base system via persisted metadata.

Pins that ``build_manufacturing_answer_service(system)`` composes the safety overlay over a plain 001
base system (the same code path the Postgres ProductionSystem uses), resolving
``ManufacturingDocumentMetadata`` from the persisted ``Document.metadata`` — both the in-memory
dataclass form AND the Postgres jsonb-dict form — with no in-process ``_mfg_meta`` dict. The high-risk
approved+effective gate (incl. the GAP-S3 demote) therefore fires on the deployed answer path.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY
from raku_rag.manufacturing.wiring import (
    build_manufacturing_answer_service,
    registry_mfg_meta_resolver,
)
from tests.helpers import claims, fresh

T = "tenant_a"
_LOCKOUT = (
    "To disassemble the press, first stop the machine, apply lockout tagout, and release the stored "
    "hydraulic pressure before removing any guard."
)
_HIGH_RISK = "How do I disassemble the press safely?"


def _meta(
    document_id: str, status: ApprovalStatus, effective_date
) -> ManufacturingDocumentMetadata:
    return ManufacturingDocumentMetadata(
        tenant_id=T,
        document_id=document_id,
        approval_status=status,
        effective_date=effective_date,
        document_kind=DocumentKind.WORK_INSTRUCTION,
        safety_category="lockout_tagout",
        hazard_tags=("設備停止", "分解", "高圧"),
    )


def _ingest(system, document_id, text, meta, *, as_dict=False):
    """Ingest via the 001 path and stash mfg metadata on the persisted Document.metadata."""
    system.ingest_text(tenant_id=T, collection_id="c", document_id=document_id, text=text)
    doc = system.registry.get(T, document_id)
    doc.metadata[MFG_META_KEY] = meta.to_mapping() if as_dict else meta


class TestManufacturingOverlayWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()  # plain MvpSystem (same building blocks ProductionSystem exposes)
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def _answer(self, query):
        service = build_manufacturing_answer_service(self.sys)
        profile = self.sys.profiles.resolve("c")
        ans, *_ = service.answer(self.op, query, profile)
        return ans

    def test_high_risk_blocked_without_approved_citation(self) -> None:
        _ingest(self.sys, "draft_proc", _LOCKOUT, _meta("draft_proc", ApprovalStatus.DRAFT, None))
        ans = self._answer(_HIGH_RISK)
        self.assertTrue(ans.high_risk)
        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.safety_block_reason, "approved_citation_missing")

    def test_high_risk_answers_with_approved_effective_primary(self) -> None:
        _ingest(
            self.sys,
            "approved_proc",
            _LOCKOUT,
            _meta("approved_proc", ApprovalStatus.APPROVED, "2026-01-10"),
        )
        ans = self._answer(_HIGH_RISK)
        self.assertTrue(ans.high_risk)
        self.assertEqual(ans.status, "ok")
        self.assertEqual(ans.citations[0].approval_status, "approved")
        self.assertTrue(ans.requires_onsite_confirmation)

    def test_resolves_postgres_jsonb_dict_form(self) -> None:
        # Metadata stored as a jsonb dict (the Postgres form) must reconstruct + drive the overlay.
        _ingest(
            self.sys,
            "approved_dict",
            _LOCKOUT,
            _meta("approved_dict", ApprovalStatus.APPROVED, "2026-01-10"),
            as_dict=True,
        )
        resolved = registry_mfg_meta_resolver(self.sys)(T, "approved_dict")
        self.assertIsInstance(resolved, ManufacturingDocumentMetadata)
        self.assertEqual(resolved.approval_status, ApprovalStatus.APPROVED)
        ans = self._answer(_HIGH_RISK)
        self.assertEqual(ans.status, "ok")
        self.assertEqual(ans.citations[0].approval_status, "approved")

    def test_tombstoned_doc_resolves_to_none(self) -> None:
        _ingest(
            self.sys,
            "approved_proc",
            _LOCKOUT,
            _meta("approved_proc", ApprovalStatus.APPROVED, "2026-01-10"),
        )
        resolve = registry_mfg_meta_resolver(self.sys)
        self.assertIsNotNone(resolve(T, "approved_proc"))
        self.sys.deletion.delete(T, "approved_proc")
        self.assertIsNone(resolve(T, "approved_proc"))  # GAP-S2: deleted content does not resurface


if __name__ == "__main__":
    unittest.main()
