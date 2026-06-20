"""T013 — Redactor: detect/classify/mask PII & secrets (FR-024/024a).

MVP: regex-based detection for the highest-risk classes. Production extends with dictionaries/NER
and (US6) image-region + EXIF handling. Logs/prompts/eval data MUST be redacted (FR-024a).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "api_key": re.compile(r"\b(?:sk|api|key|secret)[-_][A-Za-z0-9]{12,}\b", re.IGNORECASE),
    "jp_phone": re.compile(r"\b0\d{1,4}-\d{1,4}-\d{3,4}\b"),
}

HIGH_RISK_EXIF_KEYS: tuple[str, ...] = (
    "gps",
    "gpslatitude",
    "gpslongitude",
    "gpsaltitude",
    "make",
    "model",
    "serial",
    "owner",
    "datetimeoriginal",
    "createdate",
)


@dataclass(frozen=True)
class ExifRedactionResult:
    metadata: dict
    removed_keys: tuple[str, ...]


class Redactor:
    def classify(self, text: str) -> list[tuple[str, int, int]]:
        spans: list[tuple[str, int, int]] = []
        for label, pat in _PATTERNS.items():
            for m in pat.finditer(text):
                spans.append((label, m.start(), m.end()))
        return spans

    def redact(self, text: str) -> str:
        out = text
        for label, pat in _PATTERNS.items():
            out = pat.sub(f"[REDACTED:{label}]", out)
        return out

    def has_sensitive(self, text: str) -> bool:
        return bool(self.classify(text))

    def redact_visual_text(self, text: str) -> str:
        """Redact OCR/caption text before logs, traces, eval sets, or prompt storage."""
        return self.redact(text)

    def redact_exif(
        self,
        metadata: Mapping[str, object],
        *,
        retain_keys: tuple[str, ...] = (),
    ) -> ExifRedactionResult:
        """Strip high-risk EXIF by default and redact text values that are retained."""
        retained = {key.lower() for key in retain_keys}
        safe: dict[str, object] = {}
        removed: list[str] = []
        for key, value in metadata.items():
            normalized = key.lower().replace("_", "").replace("-", "")
            if normalized not in retained and any(
                token in normalized for token in HIGH_RISK_EXIF_KEYS
            ):
                removed.append(key)
                continue
            safe[key] = self.redact(value) if isinstance(value, str) else value
        return ExifRedactionResult(metadata=safe, removed_keys=tuple(removed))
