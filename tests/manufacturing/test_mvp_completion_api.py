"""MVP Completion Sprint — list/detail API contracts (drafts, documents, audit events, citation view)."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.draft import DraftStatus, DraftType
from raku_rag.manufacturing.domain.metadata import ApprovalStatus
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta


class TestMvpCompletionApi(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.admin = claims(T, "admin")
        self.sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "admin")
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="manuals",
            document_id="mfg-uat-01",
            text="E-142 reset: step 1 power off, step 2 verify cover.",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="mfg-uat-01",
                approval_status=ApprovalStatus.PENDING_REVIEW,
            ),
        )
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="manuals",
            document_id="mfg-uat-02",
            text="Safety cover must remain installed during operation.",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="mfg-uat-02",
                approval_status=ApprovalStatus.APPROVED,
            ),
        )

    def test_list_documents_filters_by_approval_status(self) -> None:
        pending = self.sys.list_documents(self.admin, approval_status="pending_review")
        self.assertEqual({d["document_id"] for d in pending}, {"mfg-uat-01"})
        approved = self.sys.list_documents(self.admin, approval_status="approved")
        self.assertIn("mfg-uat-02", {d["document_id"] for d in approved})

    def test_get_document_detail_and_citation_source(self) -> None:
        detail = self.sys.get_document_detail(self.admin, "mfg-uat-02")
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertGreaterEqual(detail["chunk_count"], 1)
        chunk_id = detail["chunks"][0]["chunk_id"]
        view = self.sys.get_citation_source(self.admin, "mfg-uat-02", chunk_id=chunk_id)
        self.assertIsNotNone(view)
        assert view is not None
        self.assertIn("Safety cover", view["chunks"][0]["text"])
        self.assertIn("preview", view)
        self.assertEqual(view["preview"]["kind"], "text")

    def test_citation_preview_spreadsheet_cell_anchor(self) -> None:
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="manuals",
            document_id="mfg-xlsx-01",
            text="Sheet1!R2C3 torque limit 50 Nm",
            metadata=mfg_meta(tenant_id=T, document_id="mfg-xlsx-01"),
        )
        detail = self.sys.get_document_detail(self.admin, "mfg-xlsx-01")
        assert detail is not None
        chunk_id = detail["chunks"][0]["chunk_id"]
        view = self.sys.get_citation_source(self.admin, "mfg-xlsx-01", chunk_id=chunk_id)
        assert view is not None
        preview = view["preview"]
        self.assertEqual(preview["kind"], "spreadsheet")
        self.assertEqual(preview["sheet_name"], "Sheet1")
        self.assertEqual(preview["cell_range"], "Sheet1!R2C3")

    def test_list_drafts_returns_tenant_inventory(self) -> None:
        d1 = self.sys.generate_draft(
            principal=self.admin,
            kind=DraftType.CHECKLIST,
            source_document_ids=("mfg-uat-02",),
        )
        d2 = self.sys.generate_draft(
            principal=self.admin,
            kind=DraftType.FAQ,
            source_document_ids=("mfg-uat-02",),
        )
        rows = self.sys.list_drafts(T)
        ids = {d.artifact_id for d in rows}
        self.assertIn(d1.artifact_id, ids)
        self.assertIn(d2.artifact_id, ids)
        self.assertTrue(all(d.status == DraftStatus.DRAFT for d in rows))

    def test_list_audit_events_is_tenant_scoped(self) -> None:
        self.sys.generate_draft(principal=self.admin, kind=DraftType.CHECKLIST)
        payload = self.sys.list_audit_events(principal=self.admin, limit=50)
        self.assertIn("events", payload)
        self.assertGreater(payload["total"], 0)
        self.assertLessEqual(len(payload["events"]), 50)

    def test_improvement_queue_from_audit(self) -> None:
        self.sys.record_answer_feedback(
            principal=self.admin,
            rating=1,
            answer_correlation_id="ans-low-1",
            document_ids=("mfg-uat-02",),
        )
        payload = self.sys.improvement_queue(self.admin)
        self.assertGreaterEqual(payload["total"], 1)
        kinds = {i["kind"] for i in payload["items"]}
        self.assertIn("low_rating", kinds)

    def test_document_file_requires_file_ref(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("preview body")
            path = fh.name
        self.sys.ingest_manufacturing_file(
            tenant_id=T,
            collection_id="manuals",
            document_id="mfg-file-1",
            path=path,
            metadata=mfg_meta(
                tenant_id=T, document_id="mfg-file-1", approval_status=ApprovalStatus.APPROVED
            ),
        )
        payload = self.sys.get_document_file(self.admin, "mfg-file-1")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIn("content_base64", payload)
        self.assertIn(b"preview", __import__("base64").b64decode(payload["content_base64"]))
