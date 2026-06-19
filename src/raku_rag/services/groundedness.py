"""T030 — GroundednessGate (FR-014): 2-stage gate. Quality gate, NOT a security boundary (FR-014b).

(a) pre-gate: enough authorized chunks at/above score_threshold and minimum_evidence_count?
(b) post-generation evidence check: is the generated answer supported by the cited chunks?
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from raku_rag.core.text import content_terms as _terms
from raku_rag.domain.models import Chunk, QueryProfile, ScoredChunk


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    reason: str = ""
    evidence: tuple[ScoredChunk, ...] = ()


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
        return GateDecision(True, "ok")
