"""GroundednessGate — `post_check` (LIVE path, whole-answer overlap) and `claim_check` (OPT-IN,
per-claim span grounding).

Originally added for P2 (docs/production-readiness/chatbot-conversational-agent-roadmap.md), which
briefly wired `claim_check` INTO `post_check`. Adversarial review (2026-07-02) found that coupling
regressed the LIVE answer path (services/answer.py:421, run on EVERY answer the platform produces):
`claim_check` false-positives on word-spaced Japanese evidence — the extractive answer is
space-normalized (`providers/llms.py::_normalize_answer_spacing`) while the evidence is not, so the
greedy numeric-span run over-captures the glued following word — flipping correct, grounded answers
to `insufficient_evidence`. That was invisible to the golden-corpus gate but hit the real demo
corpus. `claim_check` is therefore OPT-IN now (eval runner + L3 composition), NOT run by `post_check`.

This file pins both: `post_check`'s whole-answer overlap (including that a word-spaced-Japanese
extractive answer PASSES it — the regression that must never return), and `claim_check`'s per-claim
catches, its normalization guards, AND the word-spaced-Japanese false positive that is exactly why it
must stay off the live path.
"""

from __future__ import annotations

import unittest

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


class GroundednessGatePostCheckTest(unittest.TestCase):
    """`post_check` runs on EVERY live answer. It is a whole-answer bag-of-words overlap only —
    deliberately NOT per-claim (see the module docstring / `claim_check`)."""

    def setUp(self) -> None:
        self.gate = GroundednessGate()

    def test_empty_answer_fails(self) -> None:
        decision = self.gate.post_check("", [_chunk("設備の点検周期は30日です。")])
        self.assertFalse(decision.passed)
        self.assertIn("empty", decision.reason)

    def test_no_term_overlap_fails(self) -> None:
        decision = self.gate.post_check(
            "This sentence shares nothing at all with the evidence chunk below.",
            [_chunk("設備の点検周期は30日です。")],
        )
        self.assertFalse(decision.passed)
        self.assertEqual(decision.reason, "insufficient_evidence: answer not supported by evidence")

    def test_supported_answer_passes(self) -> None:
        evidence = [_chunk("設備の点検は目視で実施し異常があれば保全部門に連絡します。")]
        decision = self.gate.post_check("点検は目視で実施し異常時は保全部門へ連絡する。", evidence)
        self.assertTrue(decision.passed, decision.reason)

    def test_post_check_alone_is_not_per_claim(self) -> None:
        # An answer that shares a term with its evidence passes post_check even if it asserts a value
        # present NOWHERE in the evidence — post_check is whole-answer overlap only. Catching such a
        # fabrication is `claim_check`'s job, run opt-in off the live path (see GroundednessGateClaimCheckTest).
        evidence = [_chunk("貯槽V-205の耐圧試験は水圧試験で実施する。保持時間は30分とする。")]
        fabricated = "貯槽V-205の耐圧試験は水圧試験で実施し、試験圧力は2.5MPaとする。"
        self.assertTrue(self.gate.post_check(fabricated, evidence).passed)

    def test_word_spaced_japanese_extractive_answer_passes(self) -> None:
        # THE regression the P2 coupling caused (fixed 2026-07-02, by NOT calling claim_check here):
        # word-spaced Japanese evidence ("500時間 運転") whose extractive answer is space-normalized
        # ("500時間運転ごと"). post_check must pass it — it did before P2 and must again; the real demo
        # corpus is full of this "number + space + noun" shape.
        evidence = [_chunk("ベルトの点検は500時間 運転ごとに実施する。")]
        answer = "ベルトの点検は500時間運転ごとに実施する。"
        self.assertTrue(
            self.gate.post_check(answer, evidence).passed, "must not regress the live answer path"
        )


class GroundednessGateClaimCheckTest(unittest.TestCase):
    """`claim_check` — per-claim/per-span grounding, OPT-IN (eval runner + L3 composition). Correct
    for a genuinely generative provider that could invent an unsupported number; but it false-positives
    on word-spaced Japanese, which is exactly why it is NOT on the live path (module docstring)."""

    def setUp(self) -> None:
        self.gate = GroundednessGate()

    def test_catches_a_fabricated_number(self) -> None:
        evidence = [_chunk("貯槽V-205の耐圧試験は水圧試験で実施する。保持時間は30分とする。")]
        fabricated = "貯槽V-205の耐圧試験は水圧試験で実施し、試験圧力は2.5MPaとする。"
        decision = self.gate.claim_check(fabricated, evidence)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.reason, "insufficient_evidence: unsupported claim span")

    def test_scans_the_union_of_all_evidence_chunks(self) -> None:
        evidence = [
            _chunk("設備STG-1の点検周期は30日です。", document_id="doc_a", chunk_id="doc_a:0"),
            _chunk("設備STG-2の点検周期は60日です。", document_id="doc_b", chunk_id="doc_b:0"),
        ]
        self.assertFalse(self.gate.claim_check("設備STG-1の点検周期は45日です。", evidence).passed)

    def test_purely_qualitative_answer_passes_vacuously(self) -> None:
        evidence = [_chunk("設備の点検は目視で実施し異常があれば保全部門に連絡します。")]
        self.assertTrue(self.gate.claim_check("点検は目視で実施し異常時は保全部門へ連絡する。", evidence).passed)

    def test_passes_a_genuinely_extractive_answer(self) -> None:
        evidence = [_chunk("試験圧力は設計圧の1.5倍=1.5MPaとし、保持時間は30分とする。")]
        answer = "試験圧力は設計圧の1.5倍=1.5MPaとし、保持時間は30分とする。"
        self.assertTrue(self.gate.claim_check(answer, evidence).passed, "no false negative on extractive text")

    def test_degrees_celsius_ascii_and_cjk_spelling_are_not_a_false_mismatch(self) -> None:
        # _normalize_answer_spacing rewrites "°C" -> "℃" in generated text but not in evidence;
        # claim_check canonicalizes both so this is not read as an unsupported claim.
        evidence = [_chunk("保持温度は595±15°Cとする。")]
        answer = "保持温度は595±15℃とする。"
        self.assertTrue(self.gate.claim_check(answer, evidence).passed, self.gate.claim_check(answer, evidence).reason)

    def test_glued_particle_is_not_a_false_mismatch(self) -> None:
        # _normalize_answer_spacing deletes the space in "17 が" -> "17が"; the _GLUED_PARTICLES guard
        # stops the numeric run at the particle so it is not misread as the number's unit.
        evidence = [_chunk("アラームコード TX-17 が表示された場合は保全部門に連絡します。")]
        answer = "アラームコードTX-17が表示された場合は保全部門に連絡します。"
        self.assertTrue(self.gate.claim_check(answer, evidence).passed, self.gate.claim_check(answer, evidence).reason)

    def test_false_positives_on_word_spaced_japanese_the_reason_it_is_opt_in(self) -> None:
        # The exact false positive that keeps claim_check OFF the live path: word-spaced evidence
        # ("500時間 運転") vs the space-normalized extractive answer ("500時間運転"). The greedy numeric
        # span over-captures the glued noun ("500時間運転") which the still-spaced evidence ("500時間")
        # lacks. Documented as a KNOWN limitation: a future attempt to re-wire claim_check into
        # post_check MUST first make it normalization-symmetric (so this stops failing).
        evidence = [_chunk("ベルトの点検は500時間 運転ごとに実施する。")]
        answer = "ベルトの点検は500時間運転ごとに実施する。"
        self.assertFalse(
            self.gate.claim_check(answer, evidence).passed,
            "if this ever PASSES, claim_check may be safe to reconsider for the live path",
        )


if __name__ == "__main__":
    unittest.main()
