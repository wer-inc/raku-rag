"""P1-2 — prompt-injection defense for the LIVE answer flow (production-readiness PR-002).

Retrieved context is UNTRUSTED data. Two fixed policies, enforced in ``AnswerService.answer`` so they
apply regardless of the LLM provider (effective even behind a real generative model, not just the
deterministic extractive one):

  - **User query that tries to override the system** (e.g. "ignore all previous instructions …")
    => the answer is REFUSED: status ``insufficient_evidence`` (reason ``prompt_injection``); the
    system does not generate. (the "blocked" outcome)
  - **Instructions embedded in a RETRIEVED chunk** => the instruction span is NEUTRALIZED before the
    text reaches the model (treated as inert data, never obeyed); generation proceeds grounded in the
    legitimate content and the event is logged. If neutralization leaves no usable content the normal
    groundedness gate returns ``insufficient_evidence``.

Deterministic denylist (stdlib, Track A) so it runs in the gate. Defense-in-depth: it COMPLEMENTS —
never replaces — the ACL pre-filter, groundedness gate, and manufacturing safety gate (primary
controls). Patterns are specific multi-token phrases (NOT single broad words like "override" that
appear in legitimate manufacturing text) to avoid false positives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS: tuple[str, ...] = (
    r"ignore (?:all |the )?(?:previous|prior|earlier|above) instructions?",
    r"ignore (?:your|the) (?:previous |prior )?instructions?",
    r"disregard (?:all |the )?(?:previous|prior|earlier|above)\b",
    r"forget (?:all |the )?(?:previous|prior|earlier|above) (?:instructions?|context)",
    r"you are now (?:a|an|the)\b",
    r"(?:reveal|print|show|output|repeat)(?: me)?(?: the)? (?:system|hidden|developer) prompt",
    r"do anything now",
    r"これまでの指示を無視",
    r"以前の指示を無視",
    r"上記の指示を無視",
    r"システムプロンプトを(?:表示|教え|出力)",
)
_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)
_NEUTRALIZED = "[neutralized-instruction]"


@dataclass(frozen=True)
class InjectionVerdict:
    detected: bool
    matches: tuple[str, ...] = ()


class PromptInjectionGuard:
    """Deterministic prompt-injection detector/neutralizer. Stateless and provider-agnostic."""

    def inspect(self, text: str) -> InjectionVerdict:
        """Detect override/exfiltration instructions in untrusted text (a query or a chunk)."""
        matches = tuple(m.group(0) for m in _RE.finditer(text or ""))
        return InjectionVerdict(detected=bool(matches), matches=matches)

    def neutralize(self, text: str) -> tuple[str, int]:
        """Replace embedded instruction spans with an inert marker so a model cannot obey them.

        Returns ``(sanitized_text, count_neutralized)``. Non-injection content is left untouched, so a
        chunk that merely *contains* an injected line still contributes its legitimate evidence.
        """
        count = sum(1 for _ in _RE.finditer(text or ""))
        if not count:
            return text, 0
        return _RE.sub(_NEUTRALIZED, text), count


__all__ = ["InjectionVerdict", "PromptInjectionGuard"]
