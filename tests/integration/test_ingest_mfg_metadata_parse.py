"""P1-1 — unit-level checks for `_mfg_metadata_from_body` in the answer-service ingest handler.

Verifies the deployed /internal/ingest route correctly builds ManufacturingDocumentMetadata from the
request: a single `manufacturing` block (to_mapping shape), the contract's split
`manufacturing_metadata` + `approval` blocks (with the document_type->document_kind alias), None when
absent, and that tenant_id/document_id always come from the authenticated principal/request — never the
body block (tenancy boundary).
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

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


class TestSyncApprovalPolicy(unittest.TestCase):
    """Step 0/1 — a datasource sync derives EVERY file's approval state from the saved datasource
    trust policy, never from the (forgeable) sync request body."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = _load_server()

    def test_default_datasource_is_review_required(self) -> None:
        ds = {"config": {"source_type": "s3"}}
        self.assertEqual(self.server._datasource_approval_policy(ds), "review_required")
        self.assertEqual(
            self.server._approval_from_datasource_policy(ds),
            ("pending_review", "workflow", None),
        )

    def test_trusted_datasource_is_approved_imported_effective(self) -> None:
        ds = {"config": {"approval_policy": "trusted"}}
        status, source, eff = self.server._approval_from_datasource_policy(ds)
        self.assertEqual(status, "approved")
        self.assertEqual(source, "imported")
        self.assertTrue(
            eff, "trusted source must carry an effective_date so it is approved+effective"
        )

    def test_trusted_datasource_honors_explicit_effective_date(self) -> None:
        ds = {"config": {"approval_policy": "trusted", "approval_effective_date": "2026-01-01"}}
        self.assertEqual(
            self.server._approval_from_datasource_policy(ds),
            ("approved", "imported", "2026-01-01"),
        )

    def test_unknown_policy_fails_safe_to_review_required(self) -> None:
        ds = {"config": {"approval_policy": "YOLO"}}
        self.assertEqual(self.server._datasource_approval_policy(ds), "review_required")

    def test_body_cannot_self_grant_approved_on_review_required_source(self) -> None:
        # The sync body explicitly asks for approved — it MUST be overridden to pending_review, while
        # non-approval fields (safety_category) are preserved.
        ds = {"config": {"source_type": "s3"}}
        meta = self.server._mfg_metadata_for_sync(
            {"manufacturing": {"approval_status": "approved", "safety_category": "lockout_tagout"}},
            ds,
            "t1",
            "d1",
        )
        self.assertEqual(meta.approval_status, ApprovalStatus.PENDING_REVIEW)
        self.assertIsNone(meta.effective_date)
        self.assertEqual(meta.safety_category, "lockout_tagout")
        self.assertEqual(meta.tenant_id, "t1")
        self.assertEqual(meta.document_id, "d1")

    def test_trusted_source_stamps_approved_and_keeps_body_nonapproval_fields(self) -> None:
        ds = {"config": {"approval_policy": "trusted"}}
        meta = self.server._mfg_metadata_for_sync(
            {"manufacturing": {"safety_category": "lockout_tagout"}},
            ds,
            "t1",
            "d2",
        )
        self.assertEqual(meta.approval_status, ApprovalStatus.APPROVED)
        self.assertTrue(meta.effective_date)
        self.assertEqual(meta.safety_category, "lockout_tagout")

    def test_absent_body_block_still_yields_explicit_pending_review(self) -> None:
        # No manufacturing block at all: a synced file must STILL carry an explicit pending_review
        # (never None) so it is not a silently-usable primary basis (gate _usable_primary(None) gap).
        ds = {"config": {"source_type": "s3"}}
        meta = self.server._mfg_metadata_for_sync({}, ds, "t1", "d3")
        self.assertEqual(meta.approval_status, ApprovalStatus.PENDING_REVIEW)
        self.assertEqual(meta.approval_source.value, "workflow")

    def test_mapping_profile_is_carried_as_audit_extra_without_changing_safety_fields(self) -> None:
        ds = {
            "config": {
                "source_type": "s3",
                "mapping_profile": {
                    "profile_type": "faq",
                    "required_fields": ["question", "answer"],
                    "field_mapping": {"質問": "question", "回答": "answer"},
                },
            }
        }
        meta = self.server._mfg_metadata_for_sync({}, ds, "t1", "d4")
        self.assertEqual(meta.approval_status, ApprovalStatus.PENDING_REVIEW)
        self.assertEqual(meta.extra["datasource_profile_type"], "faq")
        self.assertEqual(meta.extra["datasource_required_fields"], ["question", "answer"])
        self.assertEqual(meta.extra["datasource_mapped_fields"], ["answer", "question"])


class _HeadOnlyConnector:
    def __init__(self, info: dict[str, object]) -> None:
        self.info = info
        self.seen_refs: list[str] = []

    def object_info(self, ref: str) -> dict[str, object]:
        self.seen_refs.append(ref)
        return self.info


class TestUploadS3RefVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = _load_server()

    def test_accepts_tenant_prefixed_ref_with_matching_metadata_and_size(self) -> None:
        connector = _HeadOnlyConnector(
            {
                "content_length": 4,
                "metadata": {"raku-tenant-id": "tenant_a", "raku-upload-id": "upload_1"},
            }
        )
        ref = "s3://bucket/tenants/tenant_a/uploads/2026-06-29/doc.txt"

        with mock.patch.dict(
            os.environ,
            {"RAKU_ALLOWED_INGEST_BUCKETS": "bucket", "RAKU_MAX_DOCUMENT_BYTES": "5"},
            clear=True,
        ):
            self.server._verify_upload_s3_ref(connector, ref, "tenant_a")

        self.assertEqual(connector.seen_refs, [ref])

    def test_rejects_other_tenant_prefix_before_head_object(self) -> None:
        connector = _HeadOnlyConnector(
            {
                "content_length": 4,
                "metadata": {"raku-tenant-id": "tenant_b", "raku-upload-id": "upload_1"},
            }
        )

        with mock.patch.dict(os.environ, {"RAKU_ALLOWED_INGEST_BUCKETS": "bucket"}, clear=True):
            with self.assertRaises(PermissionError):
                self.server._verify_upload_s3_ref(
                    connector,
                    "s3://bucket/tenants/tenant_b/uploads/2026-06-29/doc.txt",
                    "tenant_a",
                )

        self.assertEqual(connector.seen_refs, [])

    def test_rejects_metadata_tenant_mismatch(self) -> None:
        connector = _HeadOnlyConnector(
            {
                "content_length": 4,
                "metadata": {"raku-tenant-id": "tenant_b", "raku-upload-id": "upload_1"},
            }
        )

        with mock.patch.dict(os.environ, {"RAKU_ALLOWED_INGEST_BUCKETS": "bucket"}, clear=True):
            with self.assertRaises(PermissionError):
                self.server._verify_upload_s3_ref(
                    connector,
                    "s3://bucket/tenants/tenant_a/uploads/2026-06-29/doc.txt",
                    "tenant_a",
                )

    def test_rejects_oversized_s3_object(self) -> None:
        connector = _HeadOnlyConnector(
            {
                "content_length": 6,
                "metadata": {"raku-tenant-id": "tenant_a", "raku-upload-id": "upload_1"},
            }
        )

        with mock.patch.dict(
            os.environ,
            {"RAKU_ALLOWED_INGEST_BUCKETS": "bucket", "RAKU_MAX_DOCUMENT_BYTES": "5"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                self.server._verify_upload_s3_ref(
                    connector,
                    "s3://bucket/tenants/tenant_a/uploads/2026-06-29/doc.txt",
                    "tenant_a",
                )

    def test_ignores_inline_data_refs(self) -> None:
        connector = _HeadOnlyConnector({})

        with mock.patch.dict(os.environ, {}, clear=True):
            self.server._verify_upload_s3_ref(connector, "data:text/plain,hello", "tenant_a")

        self.assertEqual(connector.seen_refs, [])


if __name__ == "__main__":
    unittest.main()
