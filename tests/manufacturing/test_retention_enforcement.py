"""GAP-F1 — retention ENFORCEMENT through ManufacturingSystem (FR-MFG-020, GQ2, SC-003 reuse).

expire_document delegates to the reused 001 DeletionService (tombstone + cascade): an expired doc
never reappears in search/answer/citation. run_retention_sweep finds docs whose age (from the 001
Document.created_at) exceeds the effective customer-data retention and expires them.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raku_rag.domain.models import ScopeType, SubjectType
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta


def _backdate(sys, tenant_id, document_id, *, days):
    doc = sys._mvp.registry.get(tenant_id, document_id)
    doc.created_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class TestExpireDocumentTombstones(unittest.TestCase):
    def test_expired_doc_vanishes_from_search_and_answer(self) -> None:
        sys = fresh()
        sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="press lockout disassembly body",
            metadata=mfg_meta(tenant_id=T, document_id="d1"),
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        op = claims(T, "op")
        self.assertIn("d1", [r.document_id for r in sys.search(op, "press lockout")])
        sys.expire_document(
            tenant_id=T, document_id="d1", actor=claims(T, "admin", roles=("admin",))
        )
        self.assertEqual([r.document_id for r in sys.search(op, "press lockout")], [])
        self.assertTrue(sys._mvp.registry.get(T, "d1").tombstone)
        ans = sys.answer(op, "how do I disassemble the press after lockout?")
        self.assertFalse(any(c.document_id == "d1" for c in ans.citations))


class TestRetentionSweep(unittest.TestCase):
    def test_sweep_expires_only_docs_past_retention(self) -> None:
        sys = fresh()
        for did, days in (("old", 400), ("new", 10)):
            sys.ingest_manufacturing(
                tenant_id=T,
                collection_id="c",
                document_id=did,
                text=f"{did} press lockout body",
                metadata=mfg_meta(tenant_id=T, document_id=did),
            )
            _backdate(sys, T, did, days=days)
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        op = claims(T, "op")
        admin = claims(T, "admin", roles=("admin",))
        # default customer retention = 365 days -> only 'old' (400d) is past retention.
        expired = sys.run_retention_sweep(tenant_id=T, actor=admin)
        self.assertEqual(sorted(expired), ["old"])
        self.assertEqual([r.document_id for r in sys.search(op, "press lockout")], ["new"])

    def test_sweep_is_audited(self) -> None:
        sys = fresh()
        sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="old",
            text="old body",
            metadata=mfg_meta(tenant_id=T, document_id="old"),
        )
        _backdate(sys, T, "old", days=400)
        admin = claims(T, "admin", roles=("admin",))
        sys.run_retention_sweep(tenant_id=T, actor=admin)
        actions = [(getattr(e, "action", "") or "").lower() for e in sys.audit.read_all(admin)]
        self.assertTrue(any("retention" in a or "tombstone" in a or "delet" in a for a in actions))


if __name__ == "__main__":
    unittest.main()
