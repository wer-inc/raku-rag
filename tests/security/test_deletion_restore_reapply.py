"""T048 — restored backups must re-apply tombstone/deletion log before serving."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"


class TestDeletionRestoreReapply(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")

    def test_reapply_tombstones_removes_document_restored_from_backup(self) -> None:
        text = "The retired runbook secret code is sunset orange."
        self.sys.ingest_text(tenant_id=T, collection_id="c", document_id="d1", text=text)

        result = self.sys.deletion.delete(T, "d1")
        self.assertGreaterEqual(result.tombstoned_chunks, 1)
        self.assertEqual(len(self.sys.deletion.deletion_log(T)), 1)

        # Simulate a backup restore that reintroduces document/chunk rows as live.
        restored = self.sys.ingest_text(tenant_id=T, collection_id="c", document_id="d1", text=text)
        self.assertEqual(restored.status, "succeeded")
        before_reapply = self.sys.answer(self.alice, "What is the retired runbook secret code?")
        self.assertEqual(before_reapply.status, "ok")

        applied = self.sys.deletion.reapply_tombstones(T)

        self.assertEqual(applied, 1)
        after = self.sys.answer(self.alice, "What is the retired runbook secret code?")
        self.assertEqual(after.status, "insufficient_evidence")
        self.assertEqual(after.used_chunks, ())
        self.assertEqual(self.sys.search(self.alice, "sunset orange"), [])


if __name__ == "__main__":
    unittest.main()
