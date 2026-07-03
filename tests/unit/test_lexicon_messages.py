"""★V2 tenant_lexicon messages.* — the READ side of the message namespaces.

Unlike the additive keyword namespaces, a `messages.chat` / `messages.phone` override REPLACES
the default canned string (brand tone), falling back to the hardcoded default when unset or when
the lexicon is broken (fail-open — an outage must never break chat/call handling). Safety wording
(security refusal, high-risk, insufficient-evidence) never routes through the lexicon.
"""

from __future__ import annotations

import unittest

from raku_rag.chatbot import ChatbotService
from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.lexicon import InMemoryLexiconRepository
from raku_rag.persistence.phone_models import (
    InMemoryPhoneCallRepository,
    InMemoryPhoneScenarioRepository,
)
from raku_rag.phone.orchestrator import PhoneCallService
from raku_rag.phone.scenarios import PhoneScenarioService
from raku_rag.providers.asr import DeterministicAsrProvider
from raku_rag.providers.telephony import DeterministicCallSimulator
from raku_rag.providers.tts import DeterministicTtsProvider
from raku_rag.services.lexicon import LexiconService

TENANT = "tenant_a"
ADMIN = IdentityClaims(tenant_id=TENANT, user_id="alice", roles=("tenant_admin",))

# The hardcoded defaults — asserted verbatim so a drive-by rewording of the canned strings
# (or an accidental lexicon routing of a safety string) fails loudly here.
CHAT_HANDOFF_DEFAULT = "確認依頼を受け付けました。担当者が会話内容と確認済み情報を確認します。"
CHAT_HIGH_RISK_DEFAULT = "この内容はBotだけでは確定できません。担当者に確認依頼しました。"
PHONE_HANDOFF_DEFAULT = "担当者におつなぎします。ここまでの内容を引き継ぎます。"
PHONE_CLOSING_DEFAULT = "お電話ありがとうございました。"
PHONE_INSUFFICIENT_DEFAULT = "承認済みの情報だけでは確認できませんでした。担当者におつなぎします。"


class _BrokenLexicon:
    """Simulates a lexicon backend outage: every read raises."""

    def entries(self, tenant_id: str, namespace: str) -> dict:
        raise RuntimeError("lexicon outage")


def _lexicon() -> LexiconService:
    return LexiconService(InMemoryLexiconRepository())


def _rag_should_not_run(_principal, _query, _collection_id):
    raise AssertionError("handoff paths must not reach RAG")


class _InsufficientGateway:
    """PhoneAnswerGateway double: RAG finds no approved evidence -> no-assertion transfer."""

    def answer(self, principal, text, collection_id):
        return {
            "status": "insufficient_evidence",
            "text": None,
            "citations": [],
            "confidence": None,
            "correlation_id": "trace_none",
        }


class ChatMessagesLexiconTest(unittest.TestCase):
    def _service(self, lexicon=None) -> ChatbotService:
        service = ChatbotService(_rag_should_not_run)
        if lexicon is not None:
            service._lexicon = lexicon
        return service

    def _turn_message(self, service: ChatbotService, message: str) -> tuple[str, str]:
        _, created = service.create_session(ADMIN, {"channel": "web_chat"})
        _, turn = service.submit_message(ADMIN, created["session_id"], {"message": message})
        return turn["assistant_message"]["ai_action"], turn["assistant_message"]["message"]

    def test_unset_tenant_keeps_default_wording(self) -> None:
        # No lexicon wired at all (production default until server wiring runs).
        action, message = self._turn_message(self._service(), "担当者につないでください")
        self.assertEqual(action, "handoff")
        self.assertEqual(message, CHAT_HANDOFF_DEFAULT)
        # Lexicon wired but the tenant stored nothing: byte-identical fallback.
        action, message = self._turn_message(self._service(_lexicon()), "担当者につないでください")
        self.assertEqual(action, "handoff")
        self.assertEqual(message, CHAT_HANDOFF_DEFAULT)

    def test_tenant_override_replaces_handoff_announce(self) -> None:
        lexicon = _lexicon()
        lexicon.update(
            TENANT,
            "messages.chat",
            "handoff_announce",
            ["専任スタッフにおつなぎします。少々お待ちください。", "二番目の候補は使わない"],
            actor_id="alice",
        )
        action, message = self._turn_message(self._service(lexicon), "担当者につないでください")
        self.assertEqual(action, "handoff")
        # REPLACE semantics (not additive), first non-empty list value wins.
        self.assertEqual(message, "専任スタッフにおつなぎします。少々お待ちください。")

    def test_override_is_tenant_scoped(self) -> None:
        lexicon = _lexicon()
        lexicon.update(
            "tenant_b", "messages.chat", "handoff_announce", ["他社の文言"], actor_id="bob"
        )
        action, message = self._turn_message(self._service(lexicon), "担当者につないでください")
        self.assertEqual(action, "handoff")
        self.assertEqual(message, CHAT_HANDOFF_DEFAULT)

    def test_lexicon_outage_falls_back_to_default(self) -> None:
        action, message = self._turn_message(
            self._service(_BrokenLexicon()), "担当者につないでください"
        )
        self.assertEqual(action, "handoff")
        self.assertEqual(message, CHAT_HANDOFF_DEFAULT)

    def test_high_risk_safety_wording_ignores_overrides(self) -> None:
        lexicon = _lexicon()
        for key in ("handoff_announce", "high_risk", "default"):
            lexicon.update(TENANT, "messages.chat", key, ["ブランド文言"], actor_id="alice")
        action, message = self._turn_message(
            self._service(lexicon), "訴訟も検討しています。法的にどうなりますか"
        )
        self.assertEqual(action, "handoff")
        self.assertEqual(message, CHAT_HIGH_RISK_DEFAULT)


class PhoneMessagesLexiconTest(unittest.TestCase):
    def _service(self, lexicon=None) -> PhoneCallService:
        return PhoneCallService(
            _InsufficientGateway(),
            repository=InMemoryPhoneCallRepository(),
            scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
            telephony=DeterministicCallSimulator(),
            asr=DeterministicAsrProvider(),
            tts=DeterministicTtsProvider(),
            lexicon=lexicon,
        )

    def _turn(self, service: PhoneCallService, utterance: dict, **body_extra) -> dict:
        body = {"utterances": [utterance], **body_extra}
        status, payload = service.simulate_call(ADMIN, body)
        self.assertEqual(status, 202, payload)
        return payload["turns"][0]

    def test_unset_tenant_keeps_default_wording(self) -> None:
        turn = self._turn(self._service(), {"type": "speech", "text": "人につないでください"})
        self.assertEqual(turn["ai_action"], "handoff")
        self.assertEqual(turn["ai_response_text"], PHONE_HANDOFF_DEFAULT)
        turn = self._turn(self._service(_lexicon()), {"type": "hangup"})
        self.assertEqual(turn["ai_action"], "end_call")
        self.assertEqual(turn["ai_response_text"], PHONE_CLOSING_DEFAULT)

    def test_tenant_override_replaces_announcements(self) -> None:
        lexicon = _lexicon()
        lexicon.update(
            TENANT,
            "messages.phone",
            "handoff_announce",
            ["オペレーターにおつなぎいたします。そのままお待ちください。"],
            actor_id="alice",
        )
        lexicon.update(
            TENANT,
            "messages.phone",
            "closing",
            ["ご利用ありがとうございました。またのお電話をお待ちしております。"],
            actor_id="alice",
        )
        service = self._service(lexicon)
        turn = self._turn(service, {"type": "speech", "text": "人につないでください"})
        self.assertEqual(turn["ai_action"], "handoff")
        self.assertEqual(
            turn["ai_response_text"], "オペレーターにおつなぎいたします。そのままお待ちください。"
        )
        turn = self._turn(service, {"type": "hangup"})
        self.assertEqual(turn["ai_action"], "end_call")
        self.assertEqual(
            turn["ai_response_text"],
            "ご利用ありがとうございました。またのお電話をお待ちしております。",
        )

    def test_recording_disclosure_override(self) -> None:
        lexicon = _lexicon()
        lexicon.update(
            TENANT,
            "messages.phone",
            "recording_disclosure",
            ["サービス品質のため録音いたします。"],
            actor_id="alice",
        )
        service = self._service(lexicon)
        status, payload = service.simulate_call(
            ADMIN, {"utterances": [], "options": {"recording_enabled": True}}
        )
        self.assertEqual(status, 202, payload)
        status, detail = service.get_call(ADMIN, payload["call_id"])
        self.assertEqual(status, 200)
        self.assertTrue(detail["recording_disclosure_played"])
        system = [t for t in detail["transcript"] if t["speaker"] == "system"]
        self.assertEqual(system[0]["redacted_text"], "サービス品質のため録音いたします。")

    def test_lexicon_outage_falls_back_to_default(self) -> None:
        turn = self._turn(
            self._service(_BrokenLexicon()), {"type": "speech", "text": "人につないでください"}
        )
        self.assertEqual(turn["ai_action"], "handoff")
        self.assertEqual(turn["ai_response_text"], PHONE_HANDOFF_DEFAULT)

    def test_insufficient_evidence_safety_wording_ignores_overrides(self) -> None:
        lexicon = _lexicon()
        for key in ("handoff_announce", "insufficient_notice", "default"):
            lexicon.update(TENANT, "messages.phone", key, ["ブランド文言"], actor_id="alice")
        # No handoff trigger words -> the question reaches RAG, which finds no approved
        # evidence -> the no-assertion transfer wording must stay the hardcoded default.
        turn = self._turn(
            self._service(lexicon), {"type": "speech", "text": "営業時間を教えてください"}
        )
        self.assertEqual(turn["ai_action"], "handoff")
        self.assertEqual(turn["ai_response_text"], PHONE_INSUFFICIENT_DEFAULT)
        self.assertFalse(turn["safety"]["answered_with_evidence"])


if __name__ == "__main__":
    unittest.main()
