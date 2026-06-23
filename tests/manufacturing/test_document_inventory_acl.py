"""Tier-A gate for the ドキュメント一覧 inventory (``ManufacturingSystem.list_documents``).

The document-inventory read path enumerates documents for the workspace UI. Like search/answer it is
ACL-CRITICAL (top project risk: ACL leakage) — it MUST be deny-by-default and tombstone-excluding, the
same 001 isolation the rest of the system enforces. This pins that contract so a future refactor that
drops the ``can_read_document`` filter (or the tombstone exclusion) is caught on every gate.

Reuses 001: ``AclPolicy.can_read_document`` (via ``ManufacturingSystem`` over the in-memory MvpSystem),
``ScopeType``/``SubjectType`` grants, tombstone deletion. stdlib only.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.manufacturing.helpers import claims, fresh, mfg_meta

T = "tenant_mfg"
T_OTHER = "tenant_other"
COLL = "manuals"


class TestDocumentInventoryAcl(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        for doc_id in ("doc_a", "doc_b"):
            self.sys.ingest_manufacturing(
                tenant_id=T,
                collection_id=COLL,
                document_id=doc_id,
                text=f"maintenance procedure body for {doc_id}",
                metadata=mfg_meta(tenant_id=T, document_id=doc_id),
            )
        # alice is granted read on the collection; bob is a real tenant member with NO grant.
        self.sys.grant(T, ScopeType.COLLECTION, COLL, SubjectType.USER, "alice")
        self.alice = claims(T, "alice")
        self.bob = claims(T, "bob")

    def test_granted_user_sees_all_docs(self) -> None:
        ids = {d["document_id"] for d in self.sys.list_documents(self.alice, collection_id=COLL)}
        self.assertEqual(ids, {"doc_a", "doc_b"})

    def test_ungranted_user_sees_nothing(self) -> None:
        # deny-by-default: a tenant member with no grant gets an EMPTY inventory (no doc-id leakage).
        self.assertEqual(self.sys.list_documents(self.bob, collection_id=COLL), [])

    def test_tombstoned_doc_excluded(self) -> None:
        self.sys.delete_document(tenant_id=T, document_id="doc_a", actor=self.alice)
        ids = {d["document_id"] for d in self.sys.list_documents(self.alice, collection_id=COLL)}
        self.assertEqual(ids, {"doc_b"}, "a source-deleted doc must not resurface in the inventory")

    def test_cross_tenant_user_sees_nothing(self) -> None:
        # An identically-named grant in ANOTHER tenant must not expose tenant_mfg's docs (structural).
        self.sys.grant(T_OTHER, ScopeType.COLLECTION, COLL, SubjectType.USER, "outsider")
        outsider = claims(T_OTHER, "outsider")
        self.assertEqual(self.sys.list_documents(outsider, collection_id=COLL), [])

    def test_approval_status_surfaced(self) -> None:
        rows = self.sys.list_documents(self.alice, collection_id=COLL)
        self.assertTrue(all(r["approval_status"] == "approved" for r in rows))


if __name__ == "__main__":
    unittest.main()
