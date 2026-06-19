"""T041 — Chunker. MVP: structure/sentence-boundary chunking with offset mapping (FR-003a/b).

日本語境界 (。！？) と段落を尊重し、空白/バイト依存の分割をしない。各チャンクは原文上の
(start, end) code-point オフセットを保持する（引用の正確性のため）。
"""
from __future__ import annotations

import re

# sentence terminators incl. Japanese
_SENT_BOUNDARY = re.compile(r"(?<=[。．.!?！？])\s*")
_WORD = re.compile(r"\w+", re.UNICODE)


class SentenceChunker:
    def __init__(self, max_chars: int = 400) -> None:
        self.max_chars = max_chars

    def chunk(self, text: str) -> list[tuple[str, tuple[str, ...], int, tuple[int, int]]]:
        results: list[tuple[str, tuple[str, ...], int, tuple[int, int]]] = []
        position = 0
        heading: tuple[str, ...] = ()
        for para in text.split("\n\n"):
            para_start = text.find(para)
            # track markdown-ish heading as heading_path (日本語見出しも保持)
            stripped = para.strip()
            if stripped.startswith("#"):
                heading = (stripped.lstrip("#").strip(),)
                continue
            buf = ""
            buf_start = para_start
            cursor = para_start
            for sent in _SENT_BOUNDARY.split(para):
                if not sent:
                    continue
                s_start = text.find(sent, cursor)
                if s_start < 0:
                    s_start = cursor
                cursor = s_start + len(sent)
                if buf and len(buf) + len(sent) > self.max_chars:
                    results.append(
                        (buf.strip(), heading, position, (buf_start, buf_start + len(buf)))
                    )
                    position += 1
                    buf = ""
                    buf_start = s_start
                if not buf:
                    buf_start = s_start
                buf += sent
            if buf.strip():
                results.append((buf.strip(), heading, position, (buf_start, buf_start + len(buf))))
                position += 1
        return results
