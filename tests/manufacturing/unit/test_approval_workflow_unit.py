"""T069 — focused unit tests for ApprovalWorkflow (FR-MFG-004 / FR-MFG-004a).

Tests the ApprovalWorkflow UNIT in isolation (constructed directly with in-memory get/set closures,
a real MetadataEnricher over an empty InMemoryVectorStore, and an InMemoryAuditLogWriter) — no
ManufacturingSystem wiring. Covers:
  - the lightweight forward lifecycle draft -> pending_review -> approved -> obsolete,
  - approved sets approval_source=workflow and stamps approved_by + a default effective_date,
  - import_external as SOURCE OF TRUTH overriding the workflow state (approval_source=imported),
  - an unknown target status is rejected,
  - every transition / import is audited (reference IDs only).

stdlib only; additive (new file).
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import InMemoryAuditLogWriter
from raku_rag.manufacturing.domain.metadata import (
    ApprovalSource,
    ApprovalStatus,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.ingestion.approval import ApprovalWorkflow
from raku_rag.manufacturing.ingestion.metadata_enrichment import MetadataEnricher
from raku_rag.providers.vectorstores import InMemoryVectorStore

_T = "tenant-1"
_DOC = "spec1"


def _actor() -> IdentityClaims:
    return IdentityClaims(tenant_id=_T, user_id="reviewer-1", roles=("reviewer",))


class _Harness:
    """Build an ApprovalWorkflow over plain in-memory metadata closures (no system)."""

    def __init__(self, seed: ManufacturingDocumentMetadata | None = None) -> None:
        self.metas: dict[tuple[str, str], ManufacturingDocumentMetadata] = {}
        if seed is not None:
            self.metas[(seed.tenant_id, seed.document_id)] = seed
        self.audit = InMemoryAuditLogWriter()
        # An empty vector store: enricher.attach finds no document/chunks but is a no-op-safe call.
        enricher = MetadataEnricher(store=InMemoryVectorStore(), get_document=lambda t, d: None)
        self.wf = ApprovalWorkflow(
            get_meta=lambda t, d: self.metas.get((t, d)),
            set_meta=lambda t, d, m: self.metas.__setitem__((t, d), m),
            audit=self.audit,
            enricher=enricher,
        )


def _draft_meta() -> ManufacturingDocumentMetadata:
    return ManufacturingDocumentMetadata(
        tenant_id=_T, document_id=_DOC, approval_status=ApprovalStatus.DRAFT
    )


class TestLightweightLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.h = _Harness(seed=_draft_meta())

    def test_forward_transitions_draft_to_obsolete(self) -> None:
        s1 = self.h.wf.transition(_T, _DOC, "pending_review", _actor())
        self.assertEqual(s1.approval_status, "pending_review")
        self.assertEqual(s1.approval_source, "workflow")

        s2 = self.h.wf.transition(_T, _DOC, "approved", _actor())
        self.assertEqual(s2.approval_status, "approved")
        self.assertEqual(s2.approval_source, "workflow")

        s3 = self.h.wf.transition(_T, _DOC, "obsolete", _actor())
        self.assertEqual(s3.approval_status, "obsolete")
        self.assertEqual(s3.approval_source, "workflow")

    def test_approve_stamps_approver_and_default_effective_date(self) -> None:
        # FR-MFG-004: a workflow approval becomes effective on approval when none was set.
        s = self.h.wf.transition(_T, _DOC, "approved", _actor())
        self.assertEqual(s.approved_by, "reviewer-1")
        self.assertTrue(s.effective_date, "approval must stamp a default effective_date")

    def test_explicit_future_effective_date_is_kept_on_approve(self) -> None:
        seed = ManufacturingDocumentMetadata(
            tenant_id=_T,
            document_id=_DOC,
            approval_status=ApprovalStatus.PENDING_REVIEW,
            effective_date="2030-01-01",
        )
        h = _Harness(seed=seed)
        s = h.wf.transition(_T, _DOC, "approved", _actor())
        self.assertEqual(s.effective_date, "2030-01-01")

    def test_unknown_status_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.h.wf.transition(_T, _DOC, "bogus", _actor())

    def test_transition_persists_to_metadata_store(self) -> None:
        self.h.wf.transition(_T, _DOC, "approved", _actor())
        stored = self.h.metas[(_T, _DOC)]
        self.assertEqual(stored.approval_status, ApprovalStatus.APPROVED)
        self.assertEqual(stored.approval_source, ApprovalSource.WORKFLOW)

    def test_transition_without_prior_metadata_seeds_a_draft(self) -> None:
        # No seed metadata: _require_meta seeds a draft so a transition can still attach.
        h = _Harness(seed=None)
        s = h.wf.transition(_T, _DOC, "pending_review", _actor())
        self.assertEqual(s.approval_status, "pending_review")


class TestImportExternalSourceOfTruth(unittest.TestCase):
    def setUp(self) -> None:
        self.h = _Harness(seed=_draft_meta())

    def test_import_overrides_workflow_state(self) -> None:
        # Local workflow drives the doc to OBSOLETE first.
        self.h.wf.transition(_T, _DOC, "approved", _actor())
        self.h.wf.transition(_T, _DOC, "obsolete", _actor())
        # Upstream import wins as source of truth.
        state = self.h.wf.import_external(
            _T,
            _DOC,
            {
                "approval_status": "approved",
                "effective_date": "2026-01-10",
                "approved_by": "qa_lead",
                "approval_source": "imported",
            },
            _actor(),
        )
        self.assertEqual(state.approval_status, "approved")
        self.assertEqual(state.approval_source, "imported")
        self.assertEqual(state.effective_date, "2026-01-10")

        stored = self.h.metas[(_T, _DOC)]
        self.assertEqual(stored.approval_status, ApprovalStatus.APPROVED)
        self.assertEqual(stored.approval_source, ApprovalSource.IMPORTED)
        self.assertEqual(stored.effective_date, "2026-01-10")

    def test_import_defaults_to_approved_when_status_absent(self) -> None:
        state = self.h.wf.import_external(_T, _DOC, {"effective_date": "2026-01-10"}, _actor())
        self.assertEqual(state.approval_status, "approved")
        self.assertEqual(state.approval_source, "imported")


class TestApprovalAudited(unittest.TestCase):
    def setUp(self) -> None:
        self.h = _Harness(seed=_draft_meta())

    def test_transition_and_import_each_audited_reference_ids_only(self) -> None:
        actor = _actor()
        before = len(self.h.audit.read_all(actor))
        self.h.wf.transition(_T, _DOC, "pending_review", actor)
        self.h.wf.import_external(
            _T, _DOC, {"approval_status": "approved", "effective_date": "2026-01-10"}, actor
        )
        entries = self.h.audit.read_all(actor)
        self.assertGreaterEqual(len(entries) - before, 2)
        # The document is referenced by ID only — no body text fields exist on the entry.
        last = entries[-1]
        self.assertTrue(_DOC in (last.resource_id or "") or _DOC in last.document_ids_used)
        self.assertEqual(last.resource_type, "document")


def _meta_at(status: ApprovalStatus) -> ManufacturingDocumentMetadata:
    return ManufacturingDocumentMetadata(tenant_id=_T, document_id=_DOC, approval_status=status)


class TestForwardOnlyTransitionGuard(unittest.TestCase):
    """GAP-F6 / data-model §B: the lightweight workflow blocks backward / obsolete-resurrection moves.

    Forward (incl. skip-ahead) and idempotent moves stay legal (the "軽量承認ワークフロー" mandate);
    only a move to a LOWER lifecycle rank raises. import_external (source of truth) bypasses the guard.
    """

    def test_backward_approved_to_draft_is_rejected(self) -> None:
        h = _Harness(seed=_meta_at(ApprovalStatus.APPROVED))
        with self.assertRaises(ValueError):
            h.wf.transition(_T, _DOC, "draft", _actor())

    def test_obsolete_to_approved_resurrection_is_rejected(self) -> None:
        h = _Harness(seed=_meta_at(ApprovalStatus.OBSOLETE))
        with self.assertRaises(ValueError):
            h.wf.transition(_T, _DOC, "approved", _actor())

    def test_pending_review_to_draft_is_rejected(self) -> None:
        h = _Harness(seed=_meta_at(ApprovalStatus.PENDING_REVIEW))
        with self.assertRaises(ValueError):
            h.wf.transition(_T, _DOC, "draft", _actor())

    def test_forward_skip_draft_to_approved_is_allowed(self) -> None:
        h = _Harness(seed=_meta_at(ApprovalStatus.DRAFT))
        self.assertEqual(
            h.wf.transition(_T, _DOC, "approved", _actor()).approval_status, "approved"
        )

    def test_idempotent_same_state_is_allowed(self) -> None:
        h = _Harness(seed=_meta_at(ApprovalStatus.APPROVED))
        self.assertEqual(
            h.wf.transition(_T, _DOC, "approved", _actor()).approval_status, "approved"
        )

    def test_import_external_bypasses_the_forward_guard(self) -> None:
        # FR-MFG-004a: imported approval is source of truth and MAY resurrect an obsolete doc.
        h = _Harness(seed=_meta_at(ApprovalStatus.OBSOLETE))
        state = h.wf.import_external(_T, _DOC, {"approval_status": "approved"}, _actor())
        self.assertEqual(state.approval_status, "approved")
        self.assertEqual(state.approval_source, "imported")


class TestSupersede(unittest.TestCase):
    """GAP-F9: obsolete-by-supersession writes superseded_by (data-model §B State Transitions)."""

    def test_supersede_obsoletes_and_records_superseded_by(self) -> None:
        h = _Harness(seed=_meta_at(ApprovalStatus.APPROVED))
        state = h.wf.supersede(_T, _DOC, "new_spec", _actor())
        self.assertEqual(state.approval_status, "obsolete")
        self.assertEqual(state.approval_source, "workflow")
        self.assertEqual(state.superseded_by, "new_spec")
        stored = h.metas[(_T, _DOC)]
        self.assertEqual(stored.approval_status, ApprovalStatus.OBSOLETE)
        self.assertEqual(stored.superseded_by, "new_spec")
        self.assertTrue(stored.obsolete_at, "supersede must stamp obsolete_at")

    def test_supersede_is_audited_reference_ids_only(self) -> None:
        h = _Harness(seed=_meta_at(ApprovalStatus.APPROVED))
        actor = _actor()
        before = len(h.audit.read_all(actor))
        h.wf.supersede(_T, _DOC, "new_spec", actor)
        entries = h.audit.read_all(actor)
        self.assertEqual(len(entries) - before, 1)
        last = entries[-1]
        self.assertEqual(last.action, "approval.supersede")
        self.assertEqual(last.resource_type, "document")
        self.assertIn(_DOC, last.document_ids_used)
        self.assertIn("new_spec", last.document_ids_used)

    def test_supersede_forward_only_is_honored(self) -> None:
        # OBSOLETE->OBSOLETE is an idempotent-forward move (legal); the guard is reused, no resurrection.
        h = _Harness(seed=_meta_at(ApprovalStatus.OBSOLETE))
        self.assertEqual(h.wf.supersede(_T, _DOC, "new_spec", _actor()).superseded_by, "new_spec")


if __name__ == "__main__":
    unittest.main()
