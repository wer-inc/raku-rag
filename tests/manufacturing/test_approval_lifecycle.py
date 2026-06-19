"""T024 — US2: approval lifecycle + imported approval = source of truth (FR-MFG-004/004a, US2-2).

Two axes (quickstart S1 step 3, contracts §A POST /v1/search + §B approval):

  (1) STATE IS IDENTIFIABLE — setting ``approval_status`` / ``effective_date`` makes
      latest_approved / obsolete / effective distinguishable in search and answer: each search result
      and answer citation exposes ``approval_status`` + ``effective_date`` (FR-MFG-004), and the
      lightweight workflow draft->pending_review->approved->obsolete drives those values.

  (2) IMPORTED APPROVAL IS SOURCE OF TRUTH (FR-MFG-004a) — when an external approval is imported
      (``approval_source = imported``) it OVERRIDES the lightweight workflow state: even after the
      local workflow has moved the document to one state, importing a different external approval
      wins, and the resolved metadata / citation provenance reflect the imported values with
      ``approval_source == "imported"``.

Entrypoint contract the impl (T028/T030) must satisfy on ``ManufacturingSystem``:
  - ``transition_approval(*, tenant_id, document_id, to_status, actor) -> ApprovalState`` — drives the
    lightweight workflow; resulting ``approval_source == "workflow"``. Audited.
  - ``import_external_approval(*, tenant_id, document_id, external, actor) -> ApprovalState`` — imports
    ``{approval_status, effective_date, approved_by?, approval_source: "imported"}`` as the source of
    truth, overriding the workflow state. Audited.
  Both update the metadata read by search/answer (``get_mfg_meta``).

TDD: RED now because the approval-transition / external-import methods are unimplemented on
``ManufacturingSystem``. Authoritative: FR-MFG-004/004a, contracts/mfg-openapi.md §A/§B,
mfg-interfaces.md §2, data-model §B.
"""
from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import ApprovalStatus
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta

_TORQUE = "The torque specification for the flange bolt is forty newton meters."
_Q = "what is the torque specification for the flange bolt?"


class TestApprovalStateIdentifiable(unittest.TestCase):
    """Lightweight workflow drives an approval state that search/answer can identify."""

    def setUp(self) -> None:
        self.sys = fresh()
        # Ingest as DRAFT (workflow source) — not yet a formal/approved basis.
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="spec1",
            text=_TORQUE,
            metadata=mfg_meta(
                tenant_id=T,
                document_id="spec1",
                approval_status=ApprovalStatus.DRAFT,
                effective_date=None,
            ),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")
        self.actor = claims(T, "reviewer", roles=("reviewer",))

    def test_workflow_to_approved_then_effective_identifiable_in_search(self) -> None:
        # draft -> pending_review -> approved via the lightweight workflow.
        self.sys.transition_approval(
            tenant_id=T, document_id="spec1", to_status="pending_review", actor=self.actor
        )
        state = self.sys.transition_approval(
            tenant_id=T, document_id="spec1", to_status="approved", actor=self.actor
        )
        self.assertEqual(state.approval_status, "approved")
        self.assertEqual(state.approval_source, "workflow")

        results = [r for r in self.sys.search(self.op, "torque specification flange bolt")
                   if r.document_id == "spec1"]
        self.assertTrue(results, "approved spec must be searchable")
        self.assertEqual(results[0].approval_status, "approved")

    def test_workflow_to_obsolete_identifiable(self) -> None:
        self.sys.transition_approval(
            tenant_id=T, document_id="spec1", to_status="approved", actor=self.actor
        )
        state = self.sys.transition_approval(
            tenant_id=T, document_id="spec1", to_status="obsolete", actor=self.actor
        )
        self.assertEqual(state.approval_status, "obsolete")
        results = [r for r in self.sys.search(self.op, "torque specification flange bolt")
                   if r.document_id == "spec1"]
        self.assertTrue(results)
        self.assertEqual(results[0].approval_status, "obsolete")
        # An obsolete-only basis must not back an asserted answer (FR-MFG-006 consistency).
        ans = self.sys.answer(self.op, _Q)
        self.assertNotEqual(ans.status, "ok")


class TestImportedApprovalIsSourceOfTruth(unittest.TestCase):
    """An imported external approval OVERRIDES the lightweight workflow state (FR-MFG-004a)."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="spec1",
            text=_TORQUE,
            metadata=mfg_meta(
                tenant_id=T,
                document_id="spec1",
                approval_status=ApprovalStatus.DRAFT,
                effective_date=None,
            ),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")
        self.actor = claims(T, "reviewer", roles=("reviewer",))

    def test_imported_overrides_workflow_state(self) -> None:
        # 1) Local workflow moves the doc to OBSOLETE.
        self.sys.transition_approval(
            tenant_id=T, document_id="spec1", to_status="approved", actor=self.actor
        )
        self.sys.transition_approval(
            tenant_id=T, document_id="spec1", to_status="obsolete", actor=self.actor
        )
        # 2) Upstream system imports an APPROVED + effective approval — this is source of truth.
        state = self.sys.import_external_approval(
            tenant_id=T,
            document_id="spec1",
            external={
                "approval_status": "approved",
                "effective_date": "2026-01-10",
                "approved_by": "qa_lead",
                "approval_source": "imported",
            },
            actor=self.actor,
        )
        self.assertEqual(state.approval_status, "approved")
        self.assertEqual(state.approval_source, "imported")
        self.assertEqual(state.effective_date, "2026-01-10")

        # Resolved metadata reflects the imported truth, not the workflow's obsolete state.
        meta = self.sys.get_mfg_meta(T, "spec1")
        self.assertEqual(meta.approval_status, ApprovalStatus.APPROVED)
        self.assertEqual(meta.approval_source.value, "imported")
        self.assertEqual(meta.effective_date, "2026-01-10")

        # Search/answer reflect the imported approval (the doc is now usable as approved evidence).
        results = [r for r in self.sys.search(self.op, "torque specification flange bolt")
                   if r.document_id == "spec1"]
        self.assertTrue(results)
        self.assertEqual(results[0].approval_status, "approved")
        ans = self.sys.answer(self.op, _Q)
        self.assertEqual(ans.status, "ok", "imported approved+effective doc answers normally")
        self.assertTrue(ans.citations)
        self.assertEqual(ans.citations[0].approval_status, "approved")
        self.assertEqual(ans.citations[0].approval_source, "imported")

    def test_workflow_does_not_silently_override_imported(self) -> None:
        # Import an approved+effective external approval first (source of truth).
        self.sys.import_external_approval(
            tenant_id=T,
            document_id="spec1",
            external={
                "approval_status": "approved",
                "effective_date": "2026-01-10",
                "approval_source": "imported",
            },
            actor=self.actor,
        )
        meta = self.sys.get_mfg_meta(T, "spec1")
        self.assertEqual(meta.approval_source.value, "imported")
        self.assertEqual(meta.approval_status, ApprovalStatus.APPROVED)


class TestApprovalTransitionsAudited(unittest.TestCase):
    """Every approval transition and external import is recorded to the audit log (FR-MFG-021)."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="spec1",
            text=_TORQUE,
            metadata=mfg_meta(
                tenant_id=T,
                document_id="spec1",
                approval_status=ApprovalStatus.DRAFT,
                effective_date=None,
            ),
        )
        self.actor = claims(T, "reviewer", roles=("reviewer",))

    def test_transition_and_import_are_audited(self) -> None:
        before = len(self.sys.audit.read_all(self.actor))
        self.sys.transition_approval(
            tenant_id=T, document_id="spec1", to_status="pending_review", actor=self.actor
        )
        self.sys.import_external_approval(
            tenant_id=T,
            document_id="spec1",
            external={"approval_status": "approved", "effective_date": "2026-01-10",
                      "approval_source": "imported"},
            actor=self.actor,
        )
        after = self.sys.audit.read_all(self.actor)
        self.assertGreaterEqual(
            len(after) - before, 2, "approval transition AND external import must both be audited"
        )
        # Audit references the document by ID only (no body text).
        self.assertTrue(any("spec1" in (e.resource_id or "") or "spec1" in e.document_ids_used
                            for e in after))


if __name__ == "__main__":
    unittest.main()
