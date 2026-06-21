"""P1-1 — unit-level checks for `_mfg_metadata_from_body` in the answer-service ingest handler.

Verifies the deployed /internal/ingest route correctly builds ManufacturingDocumentMetadata from the
request: a single `manufacturing` block (to_mapping shape), the contract's split
`manufacturing_metadata` + `approval` blocks (with the document_type->document_kind alias), None when
absent, and that tenant_id/document_id always come from the authenticated principal/request — never the
body block (tenancy boundary).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from raku_rag.manufacturing.domain.metadata import ApprovalStatus, DocumentKind

ROOT = Path(__file__).resolve().parents[2]


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server_ingest_parse", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TestMfgMetadataFromBody(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = _load_server()

    def test_absent_returns_none(self) -> None:
        self.assertIsNone(self.server._mfg_metadata_from_body({}, "t1", "d1"))

    def test_single_manufacturing_block(self) -> None:
        meta = self.server._mfg_metadata_from_body(
            {"manufacturing": {"approval_status": "approved", "safety_category": "lockout_tagout"}},
            "t1",
            "d1",
        )
        self.assertIsNotNone(meta)
        self.assertEqual(meta.approval_status, ApprovalStatus.APPROVED)
        self.assertEqual(meta.safety_category, "lockout_tagout")
        self.assertEqual(meta.tenant_id, "t1")
        self.assertEqual(meta.document_id, "d1")

    def test_split_blocks_with_document_type_alias(self) -> None:
        meta = self.server._mfg_metadata_from_body(
            {
                "manufacturing_metadata": {
                    "document_type": "work_instruction",
                    "hazard_tags": ["設備停止"],
                },
                "approval": {"approval_status": "draft", "approval_source": "imported"},
            },
            "t1",
            "d1",
        )
        self.assertIsNotNone(meta)
        self.assertEqual(meta.document_kind, DocumentKind.WORK_INSTRUCTION)
        self.assertEqual(meta.approval_status, ApprovalStatus.DRAFT)
        self.assertEqual(meta.hazard_tags, ("設備停止",))

    def test_tenant_and_document_id_are_not_taken_from_body(self) -> None:
        # The metadata block tries to spoof a different tenant/document — must be overridden.
        meta = self.server._mfg_metadata_from_body(
            {
                "manufacturing": {
                    "tenant_id": "evil",
                    "document_id": "other",
                    "approval_status": "approved",
                }
            },
            "t1",
            "d1",
        )
        self.assertEqual(meta.tenant_id, "t1")
        self.assertEqual(meta.document_id, "d1")


if __name__ == "__main__":
    unittest.main()
