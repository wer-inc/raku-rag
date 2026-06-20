"""T063b - explicit captioning-disabled acceptance checks."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh


class TestVisualCaptioningDisabled(unittest.TestCase):
    def test_disabled_captioning_keeps_visual_search_and_answer_without_caption_cost(self) -> None:
        sys = fresh()
        tenant_id = "tenant_a"
        alice = claims(tenant_id, "alice")
        sys.grant(tenant_id, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")

        result = sys.ingest_visual_fixture(
            tenant_id=tenant_id,
            collection_id="manuals",
            document_id="panel_image",
            image=b"OCR: Pump panel shows alarm AL-42.\ncaption: optional caption",
            captioning_enabled=False,
        )
        search = sys.search(alice, "alarm AL-42", "manuals")
        answer = sys.answer(alice, "what alarm is shown?", "manuals")

        self.assertEqual(result.caption_status, "not_requested")
        self.assertEqual(result.regions[0].generated_caption_text, "")
        self.assertTrue(search)
        self.assertEqual(answer.status, "ok")
        self.assertEqual(answer.citations[0].kind, "visual")
        self.assertEqual(sys.cost.records(tenant_id, kind="captioning_cost"), ())


if __name__ == "__main__":
    unittest.main()
