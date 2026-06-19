"""T040 — Parser (PDF/Markdown/HTML/text). MVP implements text/markdown/html + NFKC normalize.

日本語対応 (FR-003a): NFKC 正規化。PDF は production で pdf parser を差し替え（同 interface）。
"""
from __future__ import annotations

import re
import unicodedata

from raku_rag.interfaces.base import Parser

_TAG = re.compile(r"<[^>]+>")
_SUPPORTED = {"text/plain", "text/markdown", "text/html"}


class TextParser(Parser):
    def supports(self, content_type: str) -> bool:
        return content_type in _SUPPORTED

    def parse(self, raw: bytes, content_type: str) -> str:
        text = raw.decode("utf-8", errors="replace")
        if content_type == "text/html":
            text = _TAG.sub(" ", text)
        text = unicodedata.normalize("NFKC", text)
        # collapse excess whitespace but keep line/paragraph boundaries
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
