"""P2 (docs/production-readiness/chatbot-conversational-agent-roadmap.md) — GroundednessGate.

No dedicated unit test file existed for this module before this change, even though it is a shared,
safety-critical gate (services/answer.py:421, run on every answer produced by the platform — not
just the chatbot's). It was previously only exercised indirectly through
tests/integration/test_eval.py, tests/manufacturing/*, tests/unit/test_core_quality.py, and similar.
This file pins `post_check` / `claim_check` directly, including the specific regression P2 closes:
a whole-answer bag-of-words overlap is not a per-claim check, so a fabricated but plausible-looking
number/identifier could previously slip through as long as the answer shared ANY term with ANY
evidence chunk.
"""

from __future__ import annotations

import unittest

from raku_rag.core.text import content_terms
from raku_rag.domain.models import Chunk
from raku_rag.services.groundedness import GroundednessGate

T = "tenant_gd"


def _chunk(text: str, *, document_id: str = "doc_1", chunk_id: str = "doc_1:0") -> Chunk:
    return Chunk(
        tenant_id=T,
        collection_id="manuals",
        document_id=document_id,
        chunk_id=chunk_id,
        text=text,
    )


def _old_whole_answer_check(answer_text: str, evidence) -> bool:
    """`post_check` in full, before P2 (whole-answer bag-of-words overlap, no per-claim check).

    Reimplemented inline rather than imported — there is nothing left to import `post_check` now
    also runs `claim_check` unconditionally. Keeping the old predicate here, next to the test that
    exercises both, is what makes the before/after regression narrative legible without needing to
    go dig up git history.
    """
    if not answer_text.strip():
        return False
    ans_terms = content_terms(answer_text)
    return any(ans_terms & content_terms(c.text) for c in evidence)


class GroundednessGatePostCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = GroundednessGate()

    def test_empty_answer_fails(self) -> None:
        decision = self.gate.post_check("", [_chunk("設備の点検周期は30日です。")])
        self.assertFalse(decision.passed)
        self.assertIn("empty", decision.reason)

    def test_no_term_overlap_fails_the_whole_answer_fast_path(self) -> None:
        decision = self.gate.post_check(
            "This sentence shares nothing at all with the evidence chunk below.",
            [_chunk("設備の点検周期は30日です。")],
        )
        self.assertFalse(decision.passed)
        self.assertEqual(decision.reason, "insufficient_evidence: answer not supported by evidence")

    def test_purely_qualitative_answer_passes_vacuously(self) -> None:
        # No numeric/identifier spans at all -> claim_check does not apply; this is not "a citation
        # for every sentence", only for claims that are actually numeric/identifier-shaped.
        evidence = [_chunk("設備の点検は目視で実施し異常があれば保全部門に連絡します。")]
        decision = self.gate.post_check("点検は目視で実施し異常時は保全部門へ連絡する。", evidence)
        self.assertTrue(decision.passed, decision.reason)

    def test_per_claim_check_catches_an_unsupported_number_the_old_whole_answer_check_missed(
        self,
    ) -> None:
        """The regression P2 closes: an answer sharing a term with its evidence (so the OLD
        whole-answer check below passes it outright) but asserting a specific pressure value that
        appears NOWHERE in that evidence — the shape of failure a genuinely generative provider
        (unlike today's extractive one) could produce.
        """
        evidence = [
            _chunk(
                "貯槽V-205の耐圧試験は水圧試験で実施する。試験圧力は設計圧の1.5倍とし、"
                "保持時間は30分とする。"
            )
        ]
        # Shares "耐圧試験"/"水圧試験"/"貯槽"/"V-205" with the evidence (whole-answer overlap holds)
        # but asserts "2.5MPa", a specific value that is not present anywhere in the evidence.
        fabricated_answer = "貯槽V-205の耐圧試験は水圧試験で実施し、試験圧力は2.5MPaとする。"

        # BEFORE: the old whole-answer-only check passes this.
        self.assertTrue(_old_whole_answer_check(fabricated_answer, evidence))

        # AFTER: post_check (now running the per-claim check too) fails it.
        decision = self.gate.post_check(fabricated_answer, evidence)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.reason, "insufficient_evidence: unsupported claim span")

        # The dedicated method reports the same failure directly.
        self.assertFalse(self.gate.claim_check(fabricated_answer, evidence).passed)

    def test_per_claim_check_scans_the_union_of_all_evidence_chunks(self) -> None:
        # A fabricated number not present in ANY evidence chunk fails even though the identifier it
        # is attached to ("STG-1") genuinely is present in one of them.
        evidence = [
            _chunk("設備STG-1の点検周期は30日です。", document_id="doc_a", chunk_id="doc_a:0"),
            _chunk("設備STG-2の点検周期は60日です。", document_id="doc_b", chunk_id="doc_b:0"),
        ]
        fabricated = "設備STG-1の点検周期は45日です。"  # "45" is not in either chunk

        decision = self.gate.post_check(fabricated, evidence)
        self.assertFalse(decision.passed)

    def test_per_claim_check_passes_a_genuinely_extractive_answer(self) -> None:
        # A verbatim-derived answer (as today's ExtractiveLLMProvider produces): every span in it is,
        # by construction, present in its own source evidence. This must NEVER fail (hard constraint:
        # the per-claim check is a strict superset of the old check, no new false negatives).
        evidence = [
            _chunk(
                "貯槽V-205の耐圧試験は水圧試験で実施する。試験圧力は設計圧の1.5倍=1.5MPaとし、"
                "保持時間は30分とする。"
            )
        ]
        extractive_answer = "試験圧力は設計圧の1.5倍=1.5MPaとし、保持時間は30分とする。"

        decision = self.gate.post_check(extractive_answer, evidence)
        self.assertTrue(decision.passed, decision.reason)

    def test_degrees_celsius_ascii_and_cjk_spelling_are_not_a_false_mismatch(self) -> None:
        # providers.llms._normalize_answer_spacing rewrites "°C" (ASCII degree + Latin C) to "℃" (one
        # CJK codepoint) in generated text but never touches evidence chunk text. Without
        # canonicalizing the two spellings, this would be a false "unsupported claim".
        evidence = [_chunk("保持温度は595±15°Cとする。")]
        answer = "保持温度は595±15℃とする。"

        decision = self.gate.post_check(answer, evidence)
        self.assertTrue(decision.passed, decision.reason)

    def test_glued_particle_after_normalization_removed_space_is_not_a_false_mismatch(self) -> None:
        # providers.llms._normalize_answer_spacing deletes the space between a digit/alnum run and
        # certain particles ("17 が" -> "17が") but never touches evidence chunk text. Unguarded, the
        # numeric-token match would misread the glued particle + following word as the number's
        # "unit" (e.g. "17が表示された") and then fail to find that in the still-spaced evidence.
        evidence = [_chunk("アラームコード TX-17 が表示された場合は保全部門に連絡します。")]
        answer = "アラームコードTX-17が表示された場合は保全部門に連絡します。"

        decision = self.gate.post_check(answer, evidence)
        self.assertTrue(decision.passed, decision.reason)


if __name__ == "__main__":
    unittest.main()
