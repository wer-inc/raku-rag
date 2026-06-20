"""Production-oriented chunking defaults for the ingest worker."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

_SENTENCE = re.compile(r"(?<=[。．.!?！？])\s*")


def estimate_tokens(text: str) -> int:
    word_count = len(text.split())
    char_count = max(1, len(text) // 4)
    return max(word_count, char_count)


@dataclass(frozen=True)
class ChunkingConfig:
    target_min_tokens: int = 250
    target_max_tokens: int = 400
    max_tokens: int = 450


@dataclass(frozen=True)
class ChunkRecord:
    text: str
    heading_path: tuple[str, ...]
    position: int
    source_range: tuple[int, int]
    metadata: Mapping[str, object] = field(default_factory=dict)
    token_count: int = 0


class TokenWindowChunker:
    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(
        self, text: str, *, metadata: Mapping[str, object] | None = None
    ) -> list[ChunkRecord]:
        records: list[ChunkRecord] = []
        heading_path: tuple[str, ...] = ()
        buffer: list[tuple[str, int, int]] = []
        position = 0
        cursor = 0

        def flush() -> None:
            nonlocal buffer, position
            if not buffer:
                return
            chunk_text = "".join(part for part, _start, _end in buffer).strip()
            if not chunk_text:
                buffer = []
                return
            start = buffer[0][1]
            end = buffer[-1][2]
            records.append(
                ChunkRecord(
                    text=chunk_text,
                    heading_path=heading_path,
                    position=position,
                    source_range=(start, end),
                    metadata=dict(metadata or {}),
                    token_count=estimate_tokens(chunk_text),
                )
            )
            position += 1
            buffer = []

        for line in text.splitlines(keepends=True):
            line_start = cursor
            line_end = cursor + len(line)
            cursor = line_end
            stripped = line.strip()
            if stripped.startswith("#"):
                flush()
                heading_path = (stripped.lstrip("#").strip(),)
                continue
            for sentence in self._split_line(line):
                sentence_start = text.find(sentence, line_start)
                if sentence_start < 0:
                    sentence_start = line_start
                sentence_end = sentence_start + len(sentence)
                candidate = "".join(part for part, _s, _e in buffer) + sentence
                if buffer and estimate_tokens(candidate) > self.config.target_max_tokens:
                    flush()
                if estimate_tokens(sentence) > self.config.max_tokens:
                    for part in self._split_oversized(sentence):
                        part_start = text.find(part, sentence_start)
                        part_end = part_start + len(part)
                        buffer.append((part, part_start, part_end))
                        flush()
                    continue
                buffer.append((sentence, sentence_start, sentence_end))
        flush()
        return records

    def _split_line(self, line: str) -> Iterable[str]:
        for sentence in _SENTENCE.split(line):
            if sentence:
                yield sentence

    def _split_oversized(self, sentence: str) -> Iterable[str]:
        words = sentence.split()
        if not words:
            step = self.config.max_tokens * 4
            for start in range(0, len(sentence), step):
                yield sentence[start : start + step]
            return
        buf: list[str] = []
        for word in words:
            candidate = " ".join([*buf, word])
            if buf and estimate_tokens(candidate) > self.config.max_tokens:
                yield " ".join(buf)
                buf = [word]
            else:
                buf.append(word)
        if buf:
            yield " ".join(buf)


def table_chunks(
    *,
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    heading_path: Sequence[str] = (),
    base_metadata: Mapping[str, object] | None = None,
    start_position: int = 0,
) -> list[ChunkRecord]:
    metadata = dict(base_metadata or {})
    records: list[ChunkRecord] = []
    heading = tuple(heading_path)
    summary = f"Table with {len(rows)} rows and columns: {', '.join(headers)}"
    records.append(
        ChunkRecord(
            text=summary,
            heading_path=heading,
            position=start_position,
            source_range=(0, 0),
            metadata={**metadata, "chunk_kind": "table_summary", "columns": list(headers)},
            token_count=estimate_tokens(summary),
        )
    )
    position = start_position + 1
    for row_index, row in enumerate(rows):
        pairs = [f"{header}: {value}" for header, value in zip(headers, row)]
        row_text = "; ".join(pairs)
        records.append(
            ChunkRecord(
                text=row_text,
                heading_path=heading,
                position=position,
                source_range=(row_index, row_index),
                metadata={**metadata, "chunk_kind": "table_row", "row_index": row_index},
                token_count=estimate_tokens(row_text),
            )
        )
        position += 1
        for column_index, (header, value) in enumerate(zip(headers, row)):
            cell_text = f"{header}: {value}"
            records.append(
                ChunkRecord(
                    text=cell_text,
                    heading_path=heading,
                    position=position,
                    source_range=(row_index, column_index),
                    metadata={
                        **metadata,
                        "chunk_kind": "table_cell",
                        "row_index": row_index,
                        "column": header,
                    },
                    token_count=estimate_tokens(cell_text),
                )
            )
            position += 1
    return records
