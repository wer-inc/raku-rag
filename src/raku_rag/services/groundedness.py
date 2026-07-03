"""T030 — GroundednessGate (FR-014): 2-stage gate. Quality gate, NOT a security boundary (FR-014b).

(a) pre-gate: enough authorized chunks at/above score_threshold and minimum_evidence_count?
(b) post-generation evidence check (`post_check`, on the LIVE answer path): the whole-answer
    bag-of-words overlap — is the generated answer supported (shares ≥1 term with some cited chunk)?

    There is ALSO a stricter, per-claim span check, `claim_check` (P2 of
    docs/production-readiness/chatbot-conversational-agent-roadmap.md): every individual numeric/
    identifier span in the answer must be traceable to the union of the evidence chunks' text. It
    exists for a genuinely generative provider that could invent an unsupported number in an
    otherwise-plausible answer (which the whole-answer overlap misses). It is deliberately NOT wired
    into `post_check`: on the current EXTRACTIVE provider it false-positives on word-spaced Japanese
    (answer text is space-normalized, evidence is not; the greedy numeric-span run then over-captures
    the glued following word), which would flip correct grounded answers to `insufficient_evidence`
    on the live path. So `claim_check` is OPT-IN, called directly only where a false positive is
    harmless: the eval runner (scored over the clean golden corpus) and L3 composition
    (defense-in-depth, non-suppressing). See `post_check`/`claim_check` for the full note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from raku_rag.core.hybrid_retrieval import (
    lexical_query_terms,
    metadata_identifier_matches,
    normalize_identifier,
    query_identifiers,
)
from raku_rag.core.text import content_terms as _terms
from raku_rag.domain.models import Chunk, QueryProfile, ScoredChunk
from raku_rag.observability.redaction import Redactor


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


# ★G2 salient-coverage gate constants (see `salient_coverage_check`).
# Kanji/katakana runs of >=2 chars are the query's own content words; hiragana runs (particles,
# inflection, politeness glue — "その/の/を教えて") are exactly the dilution that made the naive
# all-content-terms fraction unable to separate a legit short JP follow-up (0.17 vs its correct doc)
# from irrelevant English evidence (0.14–0.38). Bigrams WITHIN a strong run keep matching robust to
# compound splits (温度センサ vs センサ) while never crossing a particle boundary.
_STRONG_CJK_RUN_RE = re.compile(r"[㐀-鿿豈-﫿ァ-ヶー]{2,}")
_ASCII_TERM_RE = re.compile(r"^[a-z0-9]+$")
# "At least half of the question's salient terms must appear in the used evidence." Measured
# separation over the golden corpus + chatbot/phone/U19 follow-up scenarios (2026-07-03):
# must-answer cases score >=0.667, must-refuse cases <=0.20 — 0.5 sits in the gap with margin on
# both sides (see tests/unit/test_question_coverage_gate.py::SalientCoverageCheckTest).
SALIENT_LEXICAL_COVERAGE_THRESHOLD = 0.5
# Contact/PII spans in a question ("...? contact alice@example.com or 03-1234-5678") are something
# the EVIDENCE must never be expected to contain — left in, they become salient terms/identifiers
# that dilute coverage and over-refuse an otherwise answerable question. Strip them (the same
# Redactor the hot-path trace uses) before deriving salient terms, placeholders included.
_PII_REDACTOR = Redactor()
_PII_PLACEHOLDER_RE = re.compile(r"\[REDACTED:[a-z_]+\]")


def _strip_pii(query: str) -> str:
    return _PII_PLACEHOLDER_RE.sub(" ", _PII_REDACTOR.redact(query))


def _salient_query_terms(query: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(identifiers, lexical) — the question's SALIENT terms.

    identifiers: business identifiers per `core.hybrid_retrieval.query_identifiers` (both the
    hyphenated and compact forms of each).
    lexical: ASCII content terms from the lexical retrieval leg (stopword-filtered, >=3 chars or
    2 chars with a digit) EXCLUDING fragments of the extracted identifiers ("press"/"100" inside
    "EQ-PRESS-100" — the identifier leg already accounts for them, and counting them again lets an
    identifier-sharing but otherwise unresponsive document inflate coverage), plus bigrams within
    kanji/katakana runs (hiragana excluded — see `_STRONG_CJK_RUN_RE`).

    PII spans are stripped first (see `_strip_pii`).
    """
    query = _strip_pii(query)
    identifiers = query_identifiers(query)
    lexical: set[str] = set()
    for term in lexical_query_terms(query):
        if not _ASCII_TERM_RE.match(term):
            continue
        if any(
            term in identifier or term in identifier.replace("-", "") for identifier in identifiers
        ):
            continue
        lexical.add(term)
    for run in _STRONG_CJK_RUN_RE.findall(query):
        lexical.update(run[i : i + 2] for i in range(len(run) - 1))
    return identifiers, tuple(sorted(lexical))


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
        # NB: `post_check` deliberately does NOT call `claim_check` here. `claim_check` is a STRICTER
        # per-span check that is correct for a genuinely generative provider, but on the current
        # EXTRACTIVE provider it false-positives on word-spaced Japanese evidence: the extractive
        # answer is normalized (`providers/llms.py::_normalize_answer_spacing` collapses CJK-CJK
        # spaces) while the evidence is not, so the greedy numeric-span run over-captures the glued
        # following word and no longer matches the still-spaced evidence — flipping a correct,
        # grounded answer to `insufficient_evidence`. That regression hit the real demo corpus while
        # staying invisible to the golden-corpus gate. Since `post_check` runs on EVERY live answer
        # (services/answer.py), coupling `claim_check` into it made the deterministic floor WORSE than
        # before. `claim_check` therefore stays an OPT-IN check, called directly by callers that can
        # tolerate/need it: the eval runner (scored, over the clean golden corpus) and L3 composition
        # (defense-in-depth, non-suppressing). Restoring live per-claim gating for a real generative
        # provider needs `claim_check` made normalization-symmetric first (separate, tested change).
        return GateDecision(True, "ok")

    def question_coverage_check(
        self, query: str, evidence: Sequence[Chunk], threshold: float
    ) -> GateDecision:
        """★G2 no-answer gate (goal.md §1-2 「"わからない"が言えない」): the USED evidence must be
        responsive to the QUESTION, not merely internally consistent.

        `post_check` validates answer⊆evidence, so a question about content that does not exist
        (e.g. "AGVフォークリフトのバッテリー交換周期は?") could still return status=ok by extracting a
        grounded-but-irrelevant sentence that shares one incidental term ("交換"). This check
        computes the fraction of the question's content-terms present in the evidence and refuses
        below `threshold` (QueryProfile.min_question_coverage; 0 disables). Evidence-based, not
        answer-based, so it is provider-independent (a generative model paraphrases the answer but
        cannot make the evidence responsive)."""
        if threshold <= 0:
            return GateDecision(True, "ok")
        question_terms = _terms(query)
        if not question_terms:
            return GateDecision(True, "ok")
        evidence_terms: set[str] = set()
        for chunk in evidence:
            evidence_terms |= _terms(chunk.text)
        coverage = len(question_terms & evidence_terms) / len(question_terms)
        if coverage < threshold:
            return GateDecision(
                False,
                "insufficient_evidence: evidence does not cover the question "
                f"(coverage={coverage:.2f} < {threshold:.2f})",
            )
        return GateDecision(True, "ok")

    def salient_coverage_check(self, query: str, evidence: Sequence[Chunk]) -> GateDecision:
        """★G2 root-cause no-answer gate (goal.md §1-2 「"わからない"が言えない」), default-ON.

        `question_coverage_check` above (the first attempt, opt-in via
        QueryProfile.min_question_coverage) measured coverage over ALL content terms, which cannot
        separate a legit short Japanese follow-up from irrelevant English evidence — particles/
        inflection dilute the CJK-bigram term set. This check instead derives the question's
        SALIENT terms (business identifiers + ASCII content words + kanji/katakana-run bigrams; see
        `_salient_query_terms`) and requires the USED evidence to cover them:

        - every extracted identifier must appear in the evidence (chunk text, document_id, or a hot
          metadata identifier field — document_id/metadata matter for rewritten follow-ups whose
          carried prior-turn signal is a document id, not prose); AND
        - at least `SALIENT_LEXICAL_COVERAGE_THRESHOLD` of the salient lexical terms must appear in
          the evidence text.

        A question with no salient terms at all passes (nothing to judge — never over-refuse on
        signal we could not extract). Evidence-based, not answer-based, so it is provider-
        independent, and it runs AFTER post_check on the live path (services/answer.py), gated by
        QueryProfile.salient_coverage_enabled (the kill switch).
        """
        identifiers, lexical = _salient_query_terms(query)
        if not identifiers and not lexical:
            return GateDecision(True, "ok")
        evidence_text = " ".join(chunk.text for chunk in evidence).casefold()
        if identifiers:
            id_haystack = " ".join([evidence_text] + [chunk.document_id for chunk in evidence])
            normalized_haystack = normalize_identifier(id_haystack)
            compact_haystack = normalized_haystack.replace("-", "")
            for identifier in identifiers:
                if identifier in normalized_haystack:
                    continue
                if identifier.replace("-", "") in compact_haystack:
                    continue
                if any(
                    metadata_identifier_matches(chunk.metadata, (identifier,)) for chunk in evidence
                ):
                    continue
                return GateDecision(
                    False,
                    "insufficient_evidence: evidence does not cover the question "
                    f"(identifier {identifier!r} not in evidence)",
                )
        if lexical:
            covered = sum(1 for term in lexical if term in evidence_text)
            coverage = covered / len(lexical)
            if coverage < SALIENT_LEXICAL_COVERAGE_THRESHOLD:
                return GateDecision(
                    False,
                    "insufficient_evidence: evidence does not cover the question "
                    f"(salient coverage={coverage:.2f} < "
                    f"{SALIENT_LEXICAL_COVERAGE_THRESHOLD:.2f})",
                )
        return GateDecision(True, "ok")

    def claim_check(self, answer_text: str, evidence: Sequence[Chunk]) -> GateDecision:
        """Per-claim/per-span grounding: every numeric/identifier span in `answer_text` must be
        traceable to the union of `evidence` chunks' text. An answer with no such spans (a purely
        qualitative statement) passes vacuously — this does not require a citation for every sentence,
        only for the numeric/identifier claims actually present.

        OPT-IN only (see `post_check`'s note): NOT run on the live answer path, because on the current
        extractive provider it false-positives on word-spaced Japanese. Used by the eval runner and
        L3 composition, where a false positive is either scored over the clean golden corpus or
        non-suppressing.
        """
        claimed = _claim_spans(answer_text)
        if not claimed:
            return GateDecision(True, "ok")
        supported_spans = _claim_spans(" ".join(c.text for c in evidence))
        if not claimed <= supported_spans:
            return GateDecision(False, "insufficient_evidence: unsupported claim span")
        return GateDecision(True, "ok")
