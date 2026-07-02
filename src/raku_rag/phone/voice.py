"""L001 — Voice rendering for phone turns (024 FR-L05).

`ai_response_text` is optimized for screens (markdown bullets, tables, newlines, notices).
A phone caller hears ONE short spoken passage, so `render_for_voice` produces `speech_text`:
plain sentences, no markup, capped length, with a polite continuation hint when truncated.
Citations are never spoken (they stay on the call history / operator screens); the grounding
guarantees themselves are untouched — this is presentation only.
"""

from __future__ import annotations

import re

# Tuned for ja-JP telephone speech: ~3 short sentences ≈ 10-15 seconds of Polly output.
MAX_SENTENCES = 3
MAX_CHARS = 160

_CONTINUATION_HINT = "続きをお聞きになりたい場合は、そのままお申し付けください。"

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])\s*")
_MD_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_MD_BULLET = re.compile(r"^\s*(?:[-*+・]|\d+[.)、])\s+")
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)(.+?)\1")
_URL = re.compile(r"https?://\S+|deterministic://\S+")
_SECTION_LABEL = re.compile(
    r"^(?:結論|回答|対象・前提|手順|数値基準|注意点|根拠|補足|原因|対策|判断に迷う条件|確認範囲)\s*[:：]\s*"
)
_WS = re.compile(r"[ \t　]+")


def _strip_markup(line: str) -> str:
    if _MD_TABLE_ROW.match(line):
        # Table rows read terribly; keep the cell texts joined by "、".
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        cells = [c for c in cells if c and not set(c) <= {"-", ":", " "}]
        return "、".join(cells)
    line = _MD_HEADING.sub("", line)
    line = _MD_BULLET.sub("", line)
    line = _SECTION_LABEL.sub("", line)
    line = _MD_EMPHASIS.sub(r"\2", line)
    line = _URL.sub("", line)
    return line.strip()


def _sentences(text: str) -> list[str]:
    flat: list[str] = []
    for raw_line in (text or "").splitlines():
        cleaned = _strip_markup(raw_line)
        if not cleaned:
            continue
        for part in _SENTENCE_SPLIT.split(cleaned):
            part = _WS.sub(" ", part).strip()
            if part:
                flat.append(part)
    return flat


def render_for_voice(
    text: str,
    *,
    max_sentences: int = MAX_SENTENCES,
    max_chars: int = MAX_CHARS,
) -> str:
    """Return a speakable short form of an answer/notice text.

    Keeps the leading sentences (the conclusion comes first in this codebase's answer
    formats), drops markup/URLs/section labels, and appends a continuation hint when
    content had to be cut. Never returns an empty string for non-empty input.
    """
    sentences = _sentences(text)
    if not sentences:
        return ""

    spoken: list[str] = []
    used = 0
    truncated = False
    for sentence in sentences:
        if len(spoken) >= max_sentences or (used + len(sentence)) > max_chars:
            truncated = True
            break
        # Guarantee terminal punctuation so Polly pauses naturally between sentences.
        if not re.search(r"[。！？!?]$", sentence):
            sentence += "。"
        spoken.append(sentence)
        used += len(sentence)

    if not spoken:
        # A single overlong sentence: hard-cap it rather than saying nothing.
        head = sentences[0][: max_chars - 1].rstrip() + "。"
        spoken = [head]
        truncated = len(sentences) > 1 or len(sentences[0]) > max_chars

    out = "".join(spoken)
    if truncated:
        out += _CONTINUATION_HINT
    return out
