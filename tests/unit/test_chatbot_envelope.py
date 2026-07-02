"""L1EnvelopeAnswerEngine (P1) — offline/mocked-invoker only, exactly like
test_bedrock_claude_llm.py.

No real network/Bedrock calls are made anywhere in this file.
"""

from __future__ import annotations

import unittest

from raku_rag.chatbot.answer_engine import DialogueContext, L0DeterministicAnswerEngine
from raku_rag.chatbot.envelope import (
    L1EnvelopeAnswerEngine,
    build_envelope_prompt,
    citation_id_values,
    identifier_like_tokens,
    is_envelope_grounded,
    numeric_tokens,
    parse_envelope_response,
)
from raku_rag.core.config import Settings
from raku_rag.domain.models import IdentityClaims
from raku_rag.providers.llms import BedrockClaudeLLMProvider, llm_provider_from_settings


def _principal(tenant="tenant_a", user="alice"):
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=())


def _rag_answer(
    text="対策は、アキュムレータを確認してからラインを再起動することです。",
    document_id="eq-alarm-e152-al21",
):
    return {
        "status": "ok",
        "text": text,
        "citations": [
            {
                "kind": "text",
                "document_id": document_id,
                "chunk_id": f"{document_id}:0",
                "source_id": "src",
                "version": 1,
                "retrieval_score": 0.91,
            }
        ],
        "confidence": 0.88,
        "correlation_id": "trace_rag",
    }


class _RecordingProvider:
    """A minimal LLMProvider-shaped fake that records calls, for assertions the real provider
    classes cannot make (e.g. "was generate() called at all?")."""

    model = "fake"

    def __init__(self, text: str = "", raise_error: Exception | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self._text = text
        self._raise = raise_error

    def generate(self, query: str, context) -> str:
        self.calls.append((query, context))
        if self._raise is not None:
            raise self._raise
        return self._text


def _good_envelope_provider(lead_in: str, next_step: str) -> BedrockClaudeLLMProvider:
    text = f"LEAD_IN: {lead_in}\nNEXT_STEP: {next_step}"
    return BedrockClaudeLLMProvider(model_id="m", invoker=lambda **_kwargs: text)


class EnvelopeGuardFunctionsTest(unittest.TestCase):
    def test_numeric_tokens_extracts_digit_runs_with_attached_units(self):
        self.assertEqual(numeric_tokens("圧力は1.5MPa"), {"1.5mpa"})
        self.assertEqual(numeric_tokens("30分"), {"30分"})
        self.assertEqual(numeric_tokens("トルクは12N·m"), {"12n·m"})

    def test_numeric_tokens_bundles_a_short_attached_suffix(self):
        # Deliberately broad (see envelope.py docstring): a directly-glued continuation (particles,
        # copula) up to 6 chars is bundled into the token. Harmless for the guard itself, since
        # `answer_text` is embedded verbatim in both the allowed and candidate surfaces, so the same
        # substring always tokenizes identically on both sides of the comparison.
        self.assertEqual(numeric_tokens("圧力は1.5MPaです"), {"1.5mpaです"})

    def test_numeric_tokens_empty_for_text_without_digits(self):
        self.assertEqual(numeric_tokens("根拠に基づく回答です。"), set())
        self.assertEqual(numeric_tokens(""), set())

    def test_identifier_like_tokens_extracts_id_shaped_tokens(self):
        self.assertEqual(
            identifier_like_tokens("参照: eq-alarm-e152-al21 と doc_1:0"),
            {"eq-alarm-e152-al21", "doc_1:0"},
        )

    def test_identifier_like_tokens_ignores_plain_words(self):
        self.assertEqual(identifier_like_tokens("ご質問ありがとうございます"), set())
        self.assertEqual(identifier_like_tokens("ANSWER"), set())

    def test_citation_id_values_collects_document_chunk_and_source_ids(self):
        citations = [
            {"document_id": "doc_1", "chunk_id": "doc_1:0", "source_id": "src", "version": 1}
        ]
        self.assertEqual(citation_id_values(citations), {"doc_1", "doc_1:0", "src"})

    def test_parse_envelope_response_extracts_both_lines(self):
        raw = "LEAD_IN: ご質問ありがとうございます。\nNEXT_STEP: ほかにありますか。"
        self.assertEqual(
            parse_envelope_response(raw), ("ご質問ありがとうございます。", "ほかにありますか。")
        )

    def test_parse_envelope_response_none_when_a_prefix_is_missing(self):
        self.assertIsNone(parse_envelope_response("LEAD_IN: 受け止めだけ"))
        self.assertIsNone(parse_envelope_response("NEXT_STEP: 次の一歩だけ"))
        self.assertIsNone(parse_envelope_response(""))
        self.assertIsNone(parse_envelope_response("ただの回答文だけです。"))

    def test_build_envelope_prompt_carries_question_and_answer(self):
        prompt = build_envelope_prompt("トルクは？", "12N·mです。")
        self.assertIn("トルクは？", prompt)
        self.assertIn("12N·mです。", prompt)
        self.assertIn("LEAD_IN:", prompt)
        self.assertIn("NEXT_STEP:", prompt)

    def test_is_envelope_grounded_true_when_subset(self):
        answer_text = "対策は、アキュムレータを確認してからラインを再起動することです。"
        final_text = "ご質問ありがとうございます。\n\n" + answer_text + "\n\nほかにありますか。"
        self.assertTrue(is_envelope_grounded(final_text, answer_text=answer_text, citations=[]))

    def test_is_envelope_grounded_false_on_new_numeric_token(self):
        answer_text = "対策は、アキュムレータを確認してからラインを再起動することです。"
        final_text = answer_text + "\n\n過去に52件同様の事例がありました。"
        self.assertFalse(is_envelope_grounded(final_text, answer_text=answer_text, citations=[]))

    def test_is_envelope_grounded_false_on_new_citation_id(self):
        answer_text = "対策は、アキュムレータを確認してからラインを再起動することです。"
        final_text = answer_text + "\n\ndoc-fake-999 も参考にしてください。"
        self.assertFalse(is_envelope_grounded(final_text, answer_text=answer_text, citations=[]))

    def test_is_envelope_grounded_true_when_echoing_an_existing_citation_id(self):
        answer_text = "対策は現場で確認してください。"
        citations = [{"document_id": "eq-alarm-e152-al21"}]
        final_text = answer_text + "\n\n根拠 eq-alarm-e152-al21 もあわせてご確認ください。"
        self.assertTrue(
            is_envelope_grounded(final_text, answer_text=answer_text, citations=citations)
        )


class L1EnvelopeAnswerEngineTest(unittest.TestCase):
    def setUp(self):
        self.principal = _principal()
        self.context = DialogueContext()
        self.inner = L0DeterministicAnswerEngine(
            lambda principal, query, collection_id: _rag_answer()
        )

    def test_no_llm_provider_is_byte_identical_to_inner_answer(self):
        engine = L1EnvelopeAnswerEngine(self.inner, None)

        result = engine.answer(self.principal, "アラームの対策は？", None, self.context)

        self.assertEqual(
            result, self.inner.answer(self.principal, "アラームの対策は？", None, self.context)
        )

    def test_default_extractive_provider_is_a_noop_passthrough(self):
        # Settings() defaults llm_provider="" -> ExtractiveLLMProvider; called here with no
        # retrieval context it always returns "" (see envelope.py docstring), so this is the safe
        # default behaviour for any tenant dialed to L1 without a real LLM configured.
        provider = llm_provider_from_settings(Settings())
        engine = L1EnvelopeAnswerEngine(self.inner, provider)

        result = engine.answer(self.principal, "アラームの対策は？", None, self.context)

        self.assertEqual(
            result, self.inner.answer(self.principal, "アラームの対策は？", None, self.context)
        )

    def test_mocked_llm_wraps_answer_with_ack_and_next_step_and_preserves_facts(self):
        direct = self.inner.answer(self.principal, "アラームの対策は？", None, self.context)
        provider = _good_envelope_provider(
            "ご質問ありがとうございます。アラームについてお答えします。",
            "ほかに確認したい点があれば教えてください。",
        )
        engine = L1EnvelopeAnswerEngine(self.inner, provider)

        result = engine.answer(self.principal, "アラームの対策は？", None, self.context)

        self.assertIn("ご質問ありがとうございます", result["text"])
        self.assertIn(direct["text"], result["text"])
        self.assertIn("ほかに確認したい点があれば教えてください。", result["text"])
        self.assertEqual(result["citations"], direct["citations"])
        self.assertEqual(result["status"], direct["status"])
        self.assertEqual(result["confidence"], direct["confidence"])
        self.assertEqual(result["correlation_id"], direct["correlation_id"])

    def test_guard_falls_back_verbatim_when_llm_injects_unsupported_number(self):
        direct = self.inner.answer(self.principal, "アラームの対策は？", None, self.context)
        provider = _good_envelope_provider(
            "ご質問ありがとうございます。過去に52件同様の事例がありました。",
            "ほかに確認したい点があれば教えてください。",
        )
        engine = L1EnvelopeAnswerEngine(self.inner, provider)

        result = engine.answer(self.principal, "アラームの対策は？", None, self.context)

        self.assertEqual(result, direct)

    def test_guard_falls_back_verbatim_when_llm_injects_unsupported_citation_id(self):
        direct = self.inner.answer(self.principal, "アラームの対策は？", None, self.context)
        provider = _good_envelope_provider(
            "ご質問ありがとうございます。doc-fake-999 も参考になります。",
            "ほかに確認したい点があれば教えてください。",
        )
        engine = L1EnvelopeAnswerEngine(self.inner, provider)

        result = engine.answer(self.principal, "アラームの対策は？", None, self.context)

        self.assertEqual(result, direct)

    def test_provider_exception_falls_back_verbatim(self):
        direct = self.inner.answer(self.principal, "アラームの対策は？", None, self.context)
        # BedrockClaudeLLMProvider.generate() raises RuntimeError by design when unconfigured.
        provider = BedrockClaudeLLMProvider(model_id="m", invoker=None)
        engine = L1EnvelopeAnswerEngine(self.inner, provider)

        result = engine.answer(self.principal, "アラームの対策は？", None, self.context)

        self.assertEqual(result, direct)

    def test_recording_provider_exception_falls_back_verbatim(self):
        direct = self.inner.answer(self.principal, "アラームの対策は？", None, self.context)
        provider = _RecordingProvider(raise_error=RuntimeError("boom"))
        engine = L1EnvelopeAnswerEngine(self.inner, provider)

        result = engine.answer(self.principal, "アラームの対策は？", None, self.context)

        self.assertEqual(result, direct)
        self.assertEqual(len(provider.calls), 1)

    def test_malformed_llm_response_falls_back_verbatim(self):
        direct = self.inner.answer(self.principal, "アラームの対策は？", None, self.context)
        provider = _RecordingProvider(text="これは形式に沿っていない返答です。")
        engine = L1EnvelopeAnswerEngine(self.inner, provider)

        result = engine.answer(self.principal, "アラームの対策は？", None, self.context)

        self.assertEqual(result, direct)

    def test_non_answerable_inner_result_is_not_wrapped_and_llm_is_not_called(self):
        def _rag_no_answer(principal, query, collection_id):
            return {
                "status": "insufficient_evidence",
                "text": None,
                "citations": [],
                "confidence": None,
            }

        inner = L0DeterministicAnswerEngine(_rag_no_answer)
        provider = _RecordingProvider(text="LEAD_IN: x\nNEXT_STEP: y")
        engine = L1EnvelopeAnswerEngine(inner, provider)

        result = engine.answer(self.principal, "存在しない質問", None, self.context)

        self.assertEqual(result, inner.answer(self.principal, "存在しない質問", None, self.context))
        self.assertEqual(provider.calls, [])

    def test_generate_is_called_with_no_retrieval_context(self):
        provider = _RecordingProvider(text="LEAD_IN: a\nNEXT_STEP: b")
        engine = L1EnvelopeAnswerEngine(self.inner, provider)

        engine.answer(self.principal, "アラームの対策は？", None, self.context)

        self.assertEqual(len(provider.calls), 1)
        query_arg, context_arg = provider.calls[0]
        self.assertEqual(context_arg, ())
        self.assertIn("アラームの対策は？", query_arg)

    def test_context_and_principal_are_forwarded_to_inner_engine_unchanged(self):
        captured = []

        class SpyInner:
            def answer(self, principal, query, collection_id, context):
                captured.append((principal, query, collection_id, context))
                return _rag_answer()

        engine = L1EnvelopeAnswerEngine(SpyInner(), None)
        context = DialogueContext(previous_question="前回の質問")

        engine.answer(self.principal, "今回の質問", "manuals", context)

        self.assertEqual(captured, [(self.principal, "今回の質問", "manuals", context)])


if __name__ == "__main__":
    unittest.main()
