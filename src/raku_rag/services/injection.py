"""P1-2 — prompt-injection defense for the LIVE answer flow (production-readiness PR-002).

Retrieved context is UNTRUSTED data. Two fixed policies, enforced in ``AnswerService.answer`` so they
apply regardless of the LLM provider (effective even behind a real generative model, not just the
deterministic extractive one):

  - **User query that tries to override the system** (e.g. "ignore all previous instructions …")
    => the answer is REFUSED: status ``insufficient_evidence`` (reason ``prompt_injection``); the
    system does not generate. (the "blocked" outcome)
  - **Instructions embedded in a RETRIEVED chunk** => the instruction span is NEUTRALIZED before the
    text reaches the model (treated as inert data, never obeyed); generation proceeds grounded in the
    legitimate content and the event is logged + audited. If neutralization leaves no usable content the
    normal groundedness gate returns ``insufficient_evidence``.

Deterministic denylist (stdlib, Track A) so it runs in the gate. Defense-in-depth: it COMPLEMENTS —
never replaces — the ACL pre-filter, groundedness gate, and manufacturing safety gate (primary
controls). Hardening (2026-06-21): patterns are whitespace-flexible (``\\s+``, not literal spaces) and
the text is normalized (zero-width/format chars stripped) before matching, so trivial obfuscations —
extra spaces/tabs/newlines, zero-width insertions — do not bypass; the families are broadened to
reworded overrides ("act as an unrestricted assistant", "disregard all safety policies"). Patterns stay
AI-DIRECTED (the assistant's instructions / safety policies / guardrails / system prompt) and never
match generic operational phrasing like "override the temperature setpoint safely" or "do not override
the safety interlock", which is legitimate manufacturing text. A deterministic denylist is inherently
incomplete (novel phrasings / homoglyphs can still pass) — it is one layer; ACL + groundedness + the
extractive/grounded LLM remain the primary protections, and a real generative deployment must add a
grounding/instruction-hierarchy system prompt + the NestJS Guardrails adapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS: tuple[str, ...] = (
    # --- override of the assistant's own instructions / prompt / context (AI-directed) ---
    r"ignore\s+(?:all\s+|the\s+)?(?:previous|prior|earlier|above)\s+instructions?",
    r"ignore\s+(?:your|the)\s+(?:previous\s+|prior\s+)?instructions?",
    r"(?:disregard|forget|ignore)\s+(?:all\s+|the\s+|any\s+|your\s+)?"
    r"(?:previous|prior|earlier|above)\s+(?:instructions?|context|messages?|prompts?)",
    r"disregard\s+(?:all\s+|the\s+|any\s+|your\s+)?(?:previous|prior|earlier|above)\b",
    r"forget\s+(?:all\s+|the\s+)?(?:previous|prior|earlier|above)\s+(?:instructions?|context)",
    # --- override of the assistant's safety/content CONFIGURATION (AI-directed phrasings only; NOT
    #     generic operational "override/bypass safety" which is legitimate manufacturing text) ---
    r"(?:ignore|disregard|bypass|override|violate)\s+(?:all\s+|the\s+|any\s+|your\s+)?"
    r"(?:safety|content|system)\s+(?:policies|policy|guardrails?|guidelines?|filters?)",
    r"(?:ignore|disregard|bypass)\s+(?:all\s+|the\s+|any\s+|your\s+)?(?:guardrails?|safeguards?)",
    # --- role / jailbreak reprogramming ---
    r"you\s+are\s+now\s+(?:a|an|the)\b",
    r"act\s+as\s+(?:a|an|the)?\s*(?:unrestricted|unfiltered|uncensored|jailbroken|dan\b|no[\s-]*rules?)",
    r"(?:enter|enable|activate|switch\s+to)\s+(?:developer|dan|jailbreak)\s+mode",
    r"do\s+anything\s+now",
    # --- prompt / secret exfiltration ---
    r"(?:reveal|print|show|output|repeat|dump|expose)(?:\s+me)?(?:\s+the)?\s+"
    r"(?:system|hidden|developer|initial)\s+(?:prompt|instructions?|message)",
    # --- Japanese variants ---
    r"これまでの指示を無視",
    r"以前の指示を無視",
    r"(?:上記|前)の指示を無視",
    r"システムプロンプトを(?:表示|教え|出力)",
    r"安全(?:性)?(?:制約|ガイドライン|ルール|ポリシー)を(?:無視|回避)",
)
_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)
_NEUTRALIZED = "[neutralized-instruction]"
# Zero-width / BiDi / soft-hyphen / format chars used to split a denylisted phrase ("ig<zwsp>nore").
# Stripped before matching; they are invisible so removing them from neutralized output is harmless.
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]")


def _normalize(text: str) -> str:
    """Strip zero-width/format chars so they cannot be used to break up a denylisted phrase. Whitespace
    is preserved (the patterns use ``\\s+``); only invisible confusables are removed."""
    if not text:
        return ""
    return _ZERO_WIDTH.sub("", text)


@dataclass(frozen=True)
class InjectionVerdict:
    detected: bool
    matches: tuple[str, ...] = ()


class PromptInjectionGuard:
    """Deterministic prompt-injection detector/neutralizer. Stateless and provider-agnostic."""

    def inspect(self, text: str) -> InjectionVerdict:
        """Detect override/exfiltration instructions in untrusted text (a query or a chunk)."""
        matches = tuple(m.group(0) for m in _RE.finditer(_normalize(text)))
        return InjectionVerdict(detected=bool(matches), matches=matches)

    def neutralize(self, text: str) -> tuple[str, int]:
        """Replace embedded instruction spans with an inert marker so a model cannot obey them.

        Returns ``(sanitized_text, count_neutralized)``. Non-injection content is left untouched (only
        invisible zero-width chars are removed), so a chunk that merely *contains* an injected line still
        contributes its legitimate evidence.
        """
        normalized = _normalize(text)
        count = sum(1 for _ in _RE.finditer(normalized))
        if not count:
            return text, 0
        return _RE.sub(_NEUTRALIZED, normalized), count


__all__ = ["InjectionVerdict", "PromptInjectionGuard"]
