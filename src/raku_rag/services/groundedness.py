"""T030 — GroundednessGate (FR-014): 2-stage gate. Quality gate, NOT a security boundary (FR-014b).

(a) pre-gate: enough authorized chunks at/above score_threshold and minimum_evidence_count?
(b) post-generation evidence check: is the generated answer supported by the cited chunks? This is
    TWO checks, both unconditional (no rung/profile can skip either — see `post_check`):
    (b1) whole-answer bag-of-words overlap (cheap fast-path: "no term overlap at all").
    (b2) per-claim span check (P2 of docs/production-readiness/chatbot-conversational-agent-roadmap.md):
         (b1) alone is satisfied by sharing ONE term with ONE chunk anywhere in the answer, so a
         genuinely generative provider could invent an unsupported number/identifier elsewhere in an
         otherwise-plausible answer and still pass. (b2) instead requires every individual numeric/
         identifier span in the answer to be traceable to the union of the evidence chunks' text.
         Today's extractive provider copies sentences verbatim from evidence, so every span it emits
         is trivially present in that same evidence — (b2) is a strict superset of (b1), never a new
         false negative on extractive text (a bug if it were).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from raku_rag.core.text import content_terms as _terms
from raku_rag.domain.models import Chunk, QueryProfile, ScoredChunk


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    reason: str = ""
    evidence: tuple[ScoredChunk, ...] = ()


# Mirrors the numeric/identifier token heuristics in chatbot/envelope.py (numeric_tokens /
# identifier_like_tokens), which themselves mirror providers/llms.py's `_IDENTIFIER`. Duplicated
# rather than imported: this module is the base-platform groundedness gate (used by every answer
# path, not just the chatbot), so it must not take a dependency on the chatbot layer above it.
_UNIT_CHARS = "A-Za-z%°℃μΩ·぀-ヿ一-鿿"
# `_normalize_answer_spacing` (providers/llms.py) deletes the space between a digit/alnum run and one
# of these particles for readability (e.g. "17 が表示された" -> "17が表示された") but never touches
# evidence chunk text. Left unguarded, the greedy unit-chars run below would then swallow the particle
# plus following characters as though they were the number's unit (e.g. "17が表示された"), which the
# still-spaced evidence never contains — a false "unsupported claim" caused by that cosmetic rewrite,
# not a real fabrication. Block a unit run from starting with exactly the particle set that rewrite
# glues on, so the token stops at the number (plus any genuine unit) the same way on both sides.
_GLUED_PARTICLES = "超|以上|以下|未満|以内|ごと|後|へ|で|を|に|は|と|が|も"
_NUMERIC_TOKEN_RE = re.compile(rf"\d[\d,.]*(?:(?!{_GLUED_PARTICLES})[{_UNIT_CHARS}]){{0,6}}")
_IDENTIFIER_LIKE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[A-Za-z]{1,20}(?:[_:-][A-Za-z0-9]{1,20})+"
    r"|[A-Za-z]{1,20}[0-9]{1,20}(?:[_:-][A-Za-z0-9]{1,20})*"
    r")(?![A-Za-z0-9])"
)


def _normalize_span(raw: str) -> str:
    # The extractive provider's `_normalize_answer_spacing` (providers/llms.py) rewrites "°C" (ASCII
    # degree + Latin C) to "℃" (one CJK degree-Celsius codepoint) in generated text but leaves evidence
    # chunk text untouched, so the same value can surface spelled two different ways on the two sides
    # of this comparison. Canonicalize both to "℃" so that is not read as an unsupported claim.
    return raw.lower().replace("°c", "℃")


def _claim_spans(text: str) -> set[str]:
    """Every numeric(+unit) and identifier-shaped span in `text` (lowercased, unit-canonicalized)."""
    source = text or ""
    spans = {_normalize_span(m.group(0)) for m in _NUMERIC_TOKEN_RE.finditer(source)}
    spans |= {_normalize_span(m.group(0)) for m in _IDENTIFIER_LIKE_RE.finditer(source)}
    return spans


class GroundednessGate:
    def pre_gate(self, scored: Sequence[ScoredChunk], profile: QueryProfile) -> GateDecision:
        strong = [s for s in scored if s.retrieval_score >= profile.score_threshold]
        if len(strong) < profile.minimum_evidence_count:
            return GateDecision(False, "insufficient_evidence: below score/evidence threshold")
        return GateDecision(True, "ok", tuple(strong))

    def post_check(self, answer_text: str, evidence: Sequence[Chunk]) -> GateDecision:
        if not answer_text.strip():
            return GateDecision(False, "insufficient_evidence: empty/unsupported generation")
        ans_terms = _terms(answer_text)
        supported = any(ans_terms & _terms(c.text) for c in evidence)
        if not supported:
            return GateDecision(False, "insufficient_evidence: answer not supported by evidence")
        return self.claim_check(answer_text, evidence)

    def claim_check(self, answer_text: str, evidence: Sequence[Chunk]) -> GateDecision:
        """Per-claim/per-span grounding (b2 above): every numeric/identifier span in `answer_text`
        must be traceable to the union of `evidence` chunks' text. An answer with no such spans (a
        purely qualitative statement) passes vacuously — this does not require a citation for every
        sentence, only for the numeric/identifier claims actually present.
        """
        claimed = _claim_spans(answer_text)
        if not claimed:
            return GateDecision(True, "ok")
        supported_spans = _claim_spans(" ".join(c.text for c in evidence))
        if not claimed <= supported_spans:
            return GateDecision(False, "insufficient_evidence: unsupported claim span")
        return GateDecision(True, "ok")
