"""T025 — Security hard-gate: ACL leak. 権限外チャンクが result/LLM context/citation に出ない."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestAclLeak(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        # eng-only document and sales-only document, same tenant
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="eng",
            document_id="docE",
            text="The deployment pipeline runs canary rollouts before production.",
        )
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="sales",
            document_id="docS",
            text="The sales commission rate is fifteen percent for new accounts.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "eng", SubjectType.GROUP, "eng")
        self.sys.grant(T, ScopeType.COLLECTION, "sales", SubjectType.GROUP, "sales")
        self.alice = claims(T, "alice", groups=["eng"])  # not in sales

    def test_unauthorized_doc_absent_from_search(self) -> None:
        results = self.sys.search(self.alice, "commission rate for new accounts")
        for r in results:
            self.assertNotEqual(r.chunk.document_id, "docS", "sales doc leaked to eng user")

    def test_unauthorized_doc_not_cited_and_insufficient(self) -> None:
        ans = self.sys.answer(self.alice, "what is the sales commission rate?")
        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.used_chunks, ())
        for c in ans.citations:
            self.assertNotEqual(c.document_id, "docS")

    def test_authorized_doc_is_visible(self) -> None:
        ans = self.sys.answer(self.alice, "what does the deployment pipeline do?")
        self.assertEqual(ans.status, "ok")
        self.assertTrue(any(c.document_id == "docE" for c in ans.citations))


if __name__ == "__main__":
    unittest.main()
