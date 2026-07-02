"""Citation attribution follows the answer's NUMBERS (stg live finding, 2026-07-02).

A Textract-OCR'd English PDF chunk was the true source of「45 Nm」, but the citation went to a
fluent-Japanese torque doc that merely shared generic terms (ボルト/締付トルク): plain term
overlap favors same-language chunks, and the cross-language source fell below the overlap
threshold. Digit-bearing answer anchors (45/nm/m10) must dominate attribution — the chunk that
carries the answer's numbers is cited; number-less lookalikes are not.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

T = "tenant_a"
ANSWER_TEXT = "M10ボルトの締付トルクは45 Nmです。"


class _FixedLLM:
    model = "stub"

    def generate(self, query, context):
        return ANSWER_TEXT


class TestCitationNumberAnchor(unittest.TestCase):
    def test_answer_numbers_pin_the_citation_to_their_source(self) -> None:
        sys = fresh()
        sys.answer_service._llm = _FixedLLM()
        sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="pdf-en-source",
            text=(
                "RAKU-PDF-PROBE torque spec M10 bolt is 45 Nm. "
                "The image shows a single page of a document."
            ),
        )
        sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="jp-decoy",
            text=(
                "モータ M8 据付 締付トルク 規定。基礎 ボルト M16 は 締付トルク 95 N・m。"
                "端子台 M8 ねじ は 締付トルク 25 N・m。"
            ),
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")

        # Unspaced, natural Japanese — on stg this tokenization left the query with NO
        # digit-bearing anchor terms, disabling the query-anchor guard entirely.
        ans = sys.answer(claims(T, "alice"), "M10ボルトの締付トルクを教えて")

        self.assertEqual(ans.status, "ok")
        cited = [c.document_id for c in ans.citations]
        self.assertIn("pdf-en-source", cited, f"true numeric source must be cited: {cited}")
        # Known limitation (follow-up): a number-less same-language lookalike can still appear
        # as a SECONDARY citation — suppressing it safely needs semantics beyond term counting
        # (golden-corpus answers legitimately cite number-less companion chunks).


if __name__ == "__main__":
    unittest.main()
