"""L003 — Voice rendering rules (024 FR-L05) + speech_text on turns."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.phone_models import (
    InMemoryPhoneCallRepository,
    InMemoryPhoneScenarioRepository,
)
from raku_rag.phone.orchestrator import PhoneCallService
from raku_rag.phone.scenarios import PhoneScenarioService
from raku_rag.phone.voice import render_for_voice
from raku_rag.providers.asr import DeterministicAsrProvider
from raku_rag.providers.telephony import DeterministicCallSimulator
from raku_rag.providers.tts import DeterministicTtsProvider

ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))


class TestRenderForVoice(unittest.TestCase):
    def test_short_plain_answer_is_kept(self) -> None:
        self.assertEqual(
            render_for_voice("本日の営業時間は9時から18時です。"),
            "本日の営業時間は9時から18時です。",
        )

    def test_markdown_and_section_labels_are_stripped(self) -> None:
        text = (
            "結論:\n**本日の営業時間は9時から18時です。**\n\n"
            "手順:\n- 受付に電話する\n- 1. 窓口で確認する\n\n"
            "根拠:\n- FAQ-HOURS (version 3)\nhttps://example.com/faq"
        )
        spoken = render_for_voice(text)
        self.assertNotIn("*", spoken)
        self.assertNotIn("-", spoken)
        self.assertNotIn("http", spoken)
        self.assertNotIn("結論", spoken)
        self.assertIn("本日の営業時間は9時から18時です。", spoken)

    def test_table_rows_become_speakable(self) -> None:
        text = "判断基準:\n| 項目 | 判断基準 |\n|---|---|\n| 1 | 圧力は0.5MPa以下 |"
        spoken = render_for_voice(text)
        self.assertNotIn("|", spoken)
        self.assertIn("圧力は0.5MPa以下", spoken)

    def test_long_answers_are_capped_with_continuation_hint(self) -> None:
        text = "。".join(f"文{i}はとても大事な内容です" for i in range(10)) + "。"
        spoken = render_for_voice(text)
        self.assertLessEqual(spoken.count("。"), 5)
        self.assertIn("続きをお聞きになりたい場合", spoken)
        self.assertLess(len(spoken), 260)

    def test_single_overlong_sentence_is_hard_capped(self) -> None:
        text = "あ" * 500
        spoken = render_for_voice(text)
        self.assertLessEqual(
            len(spoken), 200 + len("続きをお聞きになりたい場合は、そのままお申し付けください。")
        )
        self.assertTrue(spoken)

    def test_sentences_get_terminal_punctuation(self) -> None:
        spoken = render_for_voice("担当者におつなぎします\nここまでの内容を引き継ぎます")
        self.assertIn("担当者におつなぎします。", spoken)

    def test_empty_input(self) -> None:
        self.assertEqual(render_for_voice(""), "")
        self.assertEqual(render_for_voice("根拠:\n"), "")


class TestSpeechTextOnTurns(unittest.TestCase):
    def test_turn_payload_and_transcript_carry_speech_text(self) -> None:
        class Gateway:
            def answer(self, principal, query, collection_id):
                return {
                    "status": "ok",
                    "text": "結論:\n営業時間は9時から18時です。\n\n手順:\n- 受付に連絡する",
                    "confidence": 0.9,
                    "citations": [
                        {
                            "source_id": "faq",
                            "document_id": "FAQ-HOURS",
                            "chunk_id": "FAQ-HOURS:0",
                            "version": 1,
                            "retrieval_score": 0.9,
                            "approval_status": "approved",
                        }
                    ],
                    "correlation_id": "corr",
                    "manufacturing": {},
                }

        service = PhoneCallService(
            Gateway(),
            repository=InMemoryPhoneCallRepository(),
            scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
            telephony=DeterministicCallSimulator(),
            asr=DeterministicAsrProvider(),
            tts=DeterministicTtsProvider(),
        )
        status, payload = service.simulate_call(
            ADMIN, {"utterances": [{"type": "speech", "text": "営業時間を教えてください"}]}
        )
        self.assertEqual(status, 202)
        turn = payload["turns"][0]
        self.assertIn("speech_text", turn)
        self.assertNotIn("-", turn["speech_text"])
        self.assertIn("営業時間は9時から18時です。", turn["speech_text"])
        # UI text keeps the original formatting.
        self.assertIn("手順:", turn["ai_response_text"])

        _, detail = service.get_call(ADMIN, payload["call_id"])
        ai_turns = [t for t in detail["transcript"] if t["speaker"] == "ai"]
        self.assertTrue(all("speech_text" in t for t in ai_turns))


if __name__ == "__main__":
    unittest.main()
