"""L1 (Envelope) answer engine — P1 of
docs/production-readiness/chatbot-conversational-agent-roadmap.md.

`L1EnvelopeAnswerEngine` wraps an inner `AnswerEngine` (in practice `L0DeterministicAnswerEngine`)
and, when a real generative `LLMProvider` is configured, asks it for ONLY acknowledgment /
connective / next-step phrasing around the deterministic answer — never for facts. The envelope
prompt is intentionally its own, narrower prompt (not `providers.llms.build_grounded_prompt`, which
is for evidence-grounded fact generation): the deterministic answer text is passed as the thing to
wrap, not as retrieval evidence to answer from.

Mechanical guard (the hard safety net, not the primary defense — the prompt is designed so a
compliant model rarely trips it): the assembled final text is rendered only if every numeric token
and every citation-id-shaped token in it already appears in the deterministic answer's own text or
citations. Any violation, any parse failure, any provider exception, or no provider at all -> the
inner engine's answer is returned completely unchanged (fail open to the safe floor).
"""

from __future__ import annotations

import re
from typing import Sequence

from raku_rag.chatbot.answer_engine import AnswerEngine, DialogueContext
from raku_rag.domain.models import IdentityClaims
from raku_rag.interfaces.base import LLMProvider

LEAD_IN_PREFIX = "LEAD_IN:"
NEXT_STEP_PREFIX = "NEXT_STEP:"

_ENVELOPE_PROMPT_TEMPLATE = """あなたはチャットボットの会話担当です。ユーザーの質問と、すでに検証済みで確定している回答(ANSWER)が渡されます。

厳守事項:
- ANSWER に含まれる事実・数値・単位・日付・型式・固有名詞・引用は一切変更・追加・要約しないこと。
- あなたが書いてよいのは ANSWER の前後に添える短い会話文だけで、ANSWER 自体はここに書かないこと。
- 新しい数字・識別子・固有名詞は絶対に書かないこと(概数やカウントの数字も禁止)。

出力は必ず次の2行だけにしてください(前後に他の文や説明を書かない):
{lead_in_prefix} <質問への一言の受け止めと、回答につなげる一文>
{next_step_prefix} <次に確認するとよいことを一言提案する一文>

QUESTION: {question}

ANSWER:
{answer_text}"""

# Mirrors the identifier heuristic in providers/llms.py::_IDENTIFIER (letters+separator+digits, or
# letters directly followed by digits) — tuned for document/chunk/source id shapes like "doc_1:0" or
# "eq-alarm-e152-al21", not just bare words.
_IDENTIFIER_LIKE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[A-Za-z]{1,20}(?:[_:-][A-Za-z0-9]{1,20})+"
    r"|[A-Za-z]{1,20}[0-9]{1,20}(?:[_:-][A-Za-z0-9]{1,20})*"
    r")(?![A-Za-z0-9])"
)

# A digit run plus an optionally-attached unit (ASCII letters, common unit symbols, or a short CJK
# suffix such as "分"/"時間"/"日") glued on with no separating space, e.g. "1.5MPa", "30分", "12N·m".
# Deliberately broad/conservative: false positives only cause an unnecessary (harmless) fallback to
# the verbatim deterministic answer; false negatives would let an unsupported fact slip through.
_UNIT_CHARS = "A-Za-z%°℃μΩ·぀-ヿ一-鿿"
_NUMERIC_TOKEN_RE = re.compile(rf"\d[\d,.]*[{_UNIT_CHARS}]{{0,6}}")

_CITATION_ID_FIELDS = ("document_id", "chunk_id", "source_id")


def build_envelope_prompt(question: str, answer_text: str) -> str:
    """The envelope-only prompt: wrap `answer_text`, never re-derive or re-state its facts."""
    return _ENVELOPE_PROMPT_TEMPLATE.format(
        lead_in_prefix=LEAD_IN_PREFIX,
        next_step_prefix=NEXT_STEP_PREFIX,
        question=question,
        answer_text=answer_text,
    )


def parse_envelope_response(raw: str) -> tuple[str, str] | None:
    """Extract (lead_in, next_step) from the model's two-line response, or None if malformed."""
    lead_in = ""
    next_step = ""
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(LEAD_IN_PREFIX):
            lead_in = stripped[len(LEAD_IN_PREFIX) :].strip()
        elif stripped.startswith(NEXT_STEP_PREFIX):
            next_step = stripped[len(NEXT_STEP_PREFIX) :].strip()
    if not lead_in or not next_step:
        return None
    return lead_in, next_step


def numeric_tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _NUMERIC_TOKEN_RE.finditer(text or "")}


def identifier_like_tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _IDENTIFIER_LIKE_RE.finditer(text or "")}


def citation_id_values(citations: Sequence[dict]) -> set[str]:
    values: set[str] = set()
    for citation in citations:
        for field_name in _CITATION_ID_FIELDS:
            value = citation.get(field_name)
            if value:
                values.add(str(value).lower())
    return values


def _citation_surface(citations: Sequence[dict]) -> str:
    return " ".join(
        str(value)
        for citation in citations
        for value in citation.values()
        if value not in (None, "", [], ())
    )


def is_envelope_grounded(final_text: str, *, answer_text: str, citations: Sequence[dict]) -> bool:
    """The mechanical guard: every numeric/identifier token in `final_text` must already appear in
    the deterministic `answer_text` or in `citations` (the only facts the envelope may reference).
    """
    allowed_surface = f"{answer_text} {_citation_surface(citations)}"
    allowed_numeric = numeric_tokens(allowed_surface)
    allowed_ids = identifier_like_tokens(allowed_surface) | citation_id_values(citations)
    return (
        numeric_tokens(final_text) <= allowed_numeric
        and identifier_like_tokens(final_text) <= allowed_ids
    )


class L1EnvelopeAnswerEngine:
    """Wraps `inner` with acknowledgment/next-step phrasing from `llm_provider`, guarded.

    `llm_provider=None` (no rung-appropriate LLM configured) is a fully offline, zero-call
    passthrough — used both as an explicit off switch and as what the default
    `llm_provider_from_settings(Settings())` (`ExtractiveLLMProvider`) reduces to in practice, since
    it is called here with no retrieval context and so always returns "" (see module docstring).
    """

    def __init__(self, inner: AnswerEngine, llm_provider: LLMProvider | None) -> None:
        self._inner = inner
        self._llm = llm_provider

    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None,
        context: DialogueContext,
    ) -> dict:
        inner_answer = self._inner.answer(principal, query, collection_id, context)
        if self._llm is None:
            return inner_answer
        answer_text = str(inner_answer.get("text") or "")
        if not answer_text.strip():
            return inner_answer

        citations = list(inner_answer.get("citations") or [])
        try:
            # No retrieval context: the deterministic answer is embedded in the prompt itself, not
            # passed as evidence to answer from — this is envelope phrasing, not fact generation.
            raw = self._llm.generate(build_envelope_prompt(query, answer_text), ())
        except Exception:
            return inner_answer

        parsed = parse_envelope_response(raw)
        if parsed is None:
            return inner_answer
        lead_in, next_step = parsed
        final_text = f"{lead_in}\n\n{answer_text}\n\n{next_step}"
        if not is_envelope_grounded(final_text, answer_text=answer_text, citations=citations):
            return inner_answer
        return {**inner_answer, "text": final_text}
