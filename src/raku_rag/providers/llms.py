"""T028 — LLMProvider. MVP: deterministic extractive generator (no external service).

It only ever sees authorized context chunks (the caller guarantees pre-filtering). It composes the
answer from sentences in the provided context that overlap the query, so generated claims are
grounded in the supplied evidence — keeping the post-generation evidence check meaningful and
deterministic. Production swaps in Anthropic/OpenAI-compatible providers behind LLMProvider.
"""

from __future__ import annotations

import re
from typing import Sequence

from raku_rag.core.text import content_terms as _terms
from raku_rag.domain.models import Chunk
from raku_rag.interfaces.base import LLMProvider

_SENT = re.compile(r"[^。．.!?！？\n]+[。．.!?！？]?")


class ExtractiveLLMProvider(LLMProvider):
    model = "extractive-mvp"

    def generate(self, query: str, context: Sequence[Chunk]) -> str:
        q = _terms(query)
        best: list[tuple[int, str]] = []
        for chunk in context:
            for sent in _SENT.findall(chunk.text):
                s = sent.strip()
                if not s:
                    continue
                overlap = len(q & _terms(s))
                if overlap:
                    best.append((overlap, s))
        if not best:
            # No supporting sentence in authorized context → empty (gate will catch it).
            return ""
        best.sort(key=lambda t: t[0], reverse=True)
        return " ".join(s for _, s in best[:2])
