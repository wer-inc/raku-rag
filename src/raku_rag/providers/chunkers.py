"""T041 — Chunker. MVP: structure/sentence-boundary chunking with offset mapping (FR-003a/b).

日本語境界 (。！？) と段落を尊重し、空白/バイト依存の分割をしない。各チャンクは原文上の
(start, end) code-point オフセットを保持する（引用の正確性のため）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

# sentence terminators incl. Japanese
_SENT_BOUNDARY = re.compile(r"(?<=[。．.!?！？])\s*")
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class ChunkingProfile:
    profile_id: str
    max_chars: int
    overlap_chars: int = 0


DEFAULT_CHUNKING_PROFILE = ChunkingProfile("default_text_v1", max_chars=400, overlap_chars=0)

DOCUMENT_CHUNKING_PROFILES: dict[str, ChunkingProfile] = {
    "work_instruction": ChunkingProfile("work_instruction_v1", max_chars=520, overlap_chars=80),
    "inspection": ChunkingProfile("inspection_v1", max_chars=460, overlap_chars=60),
    "quality_report": ChunkingProfile("quality_report_v1", max_chars=700, overlap_chars=100),
    "trouble_report": ChunkingProfile("trouble_report_v1", max_chars=700, overlap_chars=100),
    "minutes": ChunkingProfile("minutes_v1", max_chars=560, overlap_chars=60),
    "ledger": ChunkingProfile("ledger_v1", max_chars=360, overlap_chars=40),
    "drawing": ChunkingProfile("drawing_v1", max_chars=320, overlap_chars=0),
    "training": ChunkingProfile("training_v1", max_chars=600, overlap_chars=80),
}


class SentenceChunker:
    config_version = "sentence-profiled-v2"

    def __init__(
        self,
        max_chars: int = 400,
        *,
        overlap_chars: int = 0,
        profiles: Mapping[str, ChunkingProfile] | None = None,
    ) -> None:
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars
        self._default_profile = ChunkingProfile(
            "default_text_v1", max_chars=max_chars, overlap_chars=overlap_chars
        )
        self._profiles = dict(profiles or DOCUMENT_CHUNKING_PROFILES)

    def chunk(self, text: str) -> list[tuple[str, tuple[str, ...], int, tuple[int, int]]]:
        return self._chunk_with_profile(text, self._default_profile)

    def chunk_document(
        self, text: str, *, metadata: Mapping[str, object] | None = None
    ) -> list[tuple[str, tuple[str, ...], int, tuple[int, int]]]:
        return self._chunk_with_profile(text, self.profile_for_metadata(metadata))

    def profile_for_metadata(self, metadata: Mapping[str, object] | None = None) -> ChunkingProfile:
        document_kind = _document_kind_from_metadata(metadata or {})
        return self._profiles.get(document_kind, self._default_profile)

    def config_for_metadata(self, metadata: Mapping[str, object] | None = None) -> dict:
        profile = self.profile_for_metadata(metadata)
        return {
            "chunking_config_version": self.config_version,
            "chunking_profile": profile.profile_id,
            "max_chunk_chars": profile.max_chars,
            "chunk_overlap_chars": profile.overlap_chars,
        }

    def _chunk_with_profile(
        self, text: str, profile: ChunkingProfile
    ) -> list[tuple[str, tuple[str, ...], int, tuple[int, int]]]:
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
                if buf and len(buf) + len(sent) > profile.max_chars:
                    results.append(
                        (buf.strip(), heading, position, (buf_start, buf_start + len(buf)))
                    )
                    position += 1
                    if profile.overlap_chars:
                        buf, buf_start = _overlap_suffix(buf, buf_start, profile.overlap_chars)
                        if buf and len(buf) + len(sent) > profile.max_chars:
                            buf = ""
                            buf_start = s_start
                    else:
                        buf = ""
                        buf_start = s_start
                if not buf:
                    buf_start = s_start
                buf += sent
            if buf.strip():
                results.append((buf.strip(), heading, position, (buf_start, buf_start + len(buf))))
                position += 1
        return results


def _document_kind_from_metadata(metadata: Mapping[str, object]) -> str:
    for key in ("document_kind", "document_type"):
        value = metadata.get(key)
        if value:
            return _enum_or_str(value)
    mfg = metadata.get("_mfg_meta") or metadata.get("manufacturing")
    if isinstance(mfg, Mapping):
        for key in ("document_kind", "document_type"):
            value = mfg.get(key)
            if value:
                return _enum_or_str(value)
    for key in ("document_kind", "document_type"):
        value = getattr(mfg, key, None)
        if value:
            return _enum_or_str(value)
    return ""


def _enum_or_str(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _overlap_suffix(buf: str, buf_start: int, overlap_chars: int) -> tuple[str, int]:
    stripped = buf.strip()
    if not stripped:
        return "", buf_start
    suffix = stripped[-overlap_chars:]
    boundary = max(suffix.rfind("。"), suffix.rfind("."), suffix.rfind(" "), suffix.rfind("\n"))
    if boundary > 0 and boundary + 1 < len(suffix):
        suffix = suffix[boundary + 1 :]
    overlap_start = buf_start + len(buf) - len(suffix)
    return suffix, overlap_start
