"""T016 — Call transcript / caller-identity redaction helpers (FR-034/043, SC-005).

Builds on the platform Redactor (`raku_rag.observability.redaction`) and adds the phone-specific
surfaces: caller phone-number masking for display, hyphen-less JP mobile/landline numbers spoken
by callers, and internal auth header material. ``redact_text`` is applied before any transcript,
handoff package, log, or export leaves the orchestrator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from raku_rag.observability.redaction import Redactor

_BASE = Redactor()

# Callers say numbers without hyphens; the base Redactor only catches hyphenated JP numbers.
_JP_PHONE_PLAIN = re.compile(r"(?<!\d)0\d{9,10}(?!\d)")
_E164 = re.compile(r"\+\d{9,15}")
_INTERNAL_AUTH = re.compile(r"(?i)x-internal-auth\s*[:=]\s*\S+")
_BEARER = re.compile(r"(?i)(?<![A-Za-z0-9])bearer\s+[A-Za-z0-9._~+/=-]{8,}")
# The base Redactor patterns are \b-bounded, and in Unicode-aware `re` Japanese characters ARE
# word characters — so「カードは4111 1111 1111 1111」or「鍵はsk-...」never hit a \b boundary and
# slip through. Phone transcripts are Japanese-first: use alnum lookarounds instead of \b.
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_API_KEY = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:sk|api|key|secret)[-_][A-Za-z0-9]{8,}(?![A-Za-z0-9])"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    flagged: bool
    classes: tuple[str, ...]


def mask_phone_number(value: str | None) -> str | None:
    """Mask a caller number for display: keep the dialing prefix and last 4 digits.

    ``+81300001234`` -> ``+81******1234`` (contract phone-rag-openapi.md example shape).
    """
    if not value:
        return None
    digits = re.sub(r"[^\d+]", "", value)
    if len(digits) <= 6:
        return "*" * len(digits)
    head = digits[:3] if digits.startswith("+") else digits[:2]
    tail = digits[-4:]
    return f"{head}{'*' * 6}{tail}"


def redact_text(text: str | None) -> RedactionResult:
    """Redact PII/secrets from transcript text before persistence/display (fail-flagged)."""
    if not text:
        return RedactionResult(text="", flagged=False, classes=())
    classes: list[str] = []
    out = text
    if _INTERNAL_AUTH.search(out):
        classes.append("internal_auth_header")
        out = _INTERNAL_AUTH.sub("[REDACTED:internal_auth]", out)
    if _BEARER.search(out):
        classes.append("bearer_token")
        out = _BEARER.sub("[REDACTED:bearer_token]", out)
    if _E164.search(out):
        classes.append("phone_number")
        out = _E164.sub(lambda m: mask_phone_number(m.group(0)) or "[REDACTED:phone]", out)
    if _JP_PHONE_PLAIN.search(out):
        classes.append("phone_number")
        out = _JP_PHONE_PLAIN.sub(
            lambda m: mask_phone_number(m.group(0)) or "[REDACTED:phone]", out
        )
    if _CARD.search(out):
        classes.append("credit_card")
        out = _CARD.sub("[REDACTED:credit_card]", out)
    if _API_KEY.search(out):
        classes.append("api_key")
        out = _API_KEY.sub("[REDACTED:api_key]", out)
    base_spans = _BASE.classify(out)
    if base_spans:
        classes.extend(sorted({label for label, _, _ in base_spans}))
        out = _BASE.redact(out)
    seen: list[str] = []
    for label in classes:
        if label not in seen:
            seen.append(label)
    return RedactionResult(text=out, flagged=bool(seen), classes=tuple(seen))


def transcript_redaction_status(results: list[RedactionResult]) -> str:
    """Roll per-turn redaction results up to the CallSession field."""
    if any(r.flagged for r in results):
        return "redacted"
    return "not_needed"
