"""Answer routing should not let unrelated visual evidence override exact text evidence."""

from __future__ import annotations

import unittest
from typing import Sequence

from raku_rag.core.errors import AnswerStatus
from raku_rag.domain.models import (
    Chunk,
    Document,
    IdentityClaims,
    Modality,
    QueryProfile,
    ScoredChunk,
)
from raku_rag.providers.llms import ExtractiveLLMProvider
from raku_rag.services.answer import AnswerService
from raku_rag.services.cost import CostService
from raku_rag.services.groundedness import GroundednessGate

T = "tenant_a"


class _FakeRetrieval:
    def __init__(self, scored: Sequence[ScoredChunk]) -> None:
        self.scored = tuple(scored)

    def retrieve(self, *_args, **_kwargs) -> list[ScoredChunk]:
        return list(self.scored)

    def is_visible(self, _principal: IdentityClaims, _chunk: Chunk) -> bool:
        return True


class _FailingVLM:
    model = "failing-vlm"

    def generate(self, *_args, **_kwargs) -> str:
        raise AssertionError("unrelated visual evidence must not route this answer to VLM")


class MixedVisualTextRoutingTest(unittest.TestCase):
    def test_identifier_matched_text_evidence_beats_unrelated_visual_context(self) -> None:
        text_chunk = Chunk(
            tenant_id=T,
            collection_id="manuals",
            document_id="text-manual",
            chunk_id="text-manual:0",
            text=(
                "設備 STG-TEXT-20260627 の正式点検周期は 90 日です。"
                "アラームコード TX-17 が表示された場合は保全部門に連絡します。"
            ),
        )
        visual_chunk = Chunk(
            tenant_id=T,
            collection_id="manuals",
            document_id="visual-panel",
            chunk_id="visual-panel:visual:1:0",
            text="VISUAL PANEL STG-VISUAL-20260627\nALARM CODE: AL-42",
            modality=Modality.VISUAL,
            metadata={
                "asset_id": "asset-1",
                "region_id": "region-1",
                "page_number": 1,
                "ocr_text": "VISUAL PANEL STG-VISUAL-20260627\nALARM CODE: AL-42",
            },
        )
        scored = (
            ScoredChunk(chunk=text_chunk, retrieval_score=1.1),
            ScoredChunk(chunk=visual_chunk, retrieval_score=1.09),
        )
        docs = {
            "text-manual": Document(T, "manuals", "text-manual", "text-source"),
            "visual-panel": Document(T, "manuals", "visual-panel", "visual-source"),
        }
        service = AnswerService(
            _FakeRetrieval(scored),  # type: ignore[arg-type]
            ExtractiveLLMProvider(),
            GroundednessGate(),
            CostService(),
            lambda _tenant_id, document_id: docs.get(document_id),
            vlm=_FailingVLM(),  # type: ignore[arg-type]
        )

        ans = service.answer(
            IdentityClaims(tenant_id=T, user_id="alice"),
            "STG-TEXT-20260627 の点検周期とアラームコードは?",
            QueryProfile(top_k=2, minimum_evidence_count=1),
        )

        self.assertEqual(ans.status, AnswerStatus.OK.value)
        self.assertIn("90 日", ans.text or "")
        self.assertIn("TX-17", ans.text or "")
        self.assertNotIn("AL-42", ans.text or "")
        self.assertEqual(ans.used_chunks, ("text-manual:0",))
        self.assertEqual([c.kind for c in ans.citations], ["text"])


if __name__ == "__main__":
    unittest.main()
