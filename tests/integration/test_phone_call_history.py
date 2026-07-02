"""T063 — Call history search filters + redacted detail projection (022 US4, FR-030/031)."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.phone_models import (
    InMemoryPhoneCallRepository,
    InMemoryPhoneScenarioRepository,
)
from raku_rag.phone.orchestrator import PhoneCallService
from raku_rag.phone.scenarios import PhoneScenarioService
from raku_rag.providers.asr import DeterministicAsrProvider
from raku_rag.providers.telephony import DeterministicCallSimulator
from raku_rag.providers.tts import DeterministicTtsProvider

ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))
QA = IdentityClaims(tenant_id="tenant_a", user_id="misaki", roles=("qa_reviewer",))
NOROLE = IdentityClaims(tenant_id="tenant_a", user_id="norole", roles=())
OTHER_TENANT = IdentityClaims(tenant_id="tenant_b", user_id="mallory", roles=("tenant_admin",))


class InsufficientGateway:
    def answer(self, principal, query, collection_id):
        return {
            "status": "insufficient_evidence", "text": "", "confidence": None,
            "citations": [], "correlation_id": "corr", "manufacturing": {},
        }


class PhoneCallHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = PhoneCallService(
            InsufficientGateway(),
            repository=InMemoryPhoneCallRepository(),
            scenarios=PhoneScenarioService(InMemoryPhoneScenarioRepository()),
            telephony=DeterministicCallSimulator(),
            asr=DeterministicAsrProvider(),
            tts=DeterministicTtsProvider(),
        )
        # Call A: speech turn -> insufficient evidence -> handoff_pending.
        _, a = self.service.simulate_call(
            ADMIN,
            {
                "caller": {"phone_number": "+81311112222", "customer_id": "cust_a"},
                "utterances": [{"type": "speech", "text": "返金の条件について"}],
            },
        )
        # Call B: immediate hangup -> terminal, different number.
        _, b = self.service.simulate_call(
            ADMIN,
            {
                "caller": {"phone_number": "+81333334444", "customer_id": "cust_b"},
                "utterances": [{"type": "hangup"}],
            },
        )
        self.call_a, self.call_b = a["call_id"], b["call_id"]

    def _items(self, query=None, principal=ADMIN):
        status, payload = self.service.list_calls(principal, query or {})
        assert status == 200, payload
        return payload["items"]

    def test_list_requires_read_role_and_is_tenant_scoped(self) -> None:
        self.assertEqual(self.service.list_calls(NOROLE, {})[0], 403)
        self.assertEqual(self._items(principal=OTHER_TENANT), [])
        self.assertEqual(len(self._items(principal=QA)), 2)

    def test_phone_number_filter_matches_last4_suffix(self) -> None:
        items = self._items({"phone_number": "2222"})
        self.assertEqual([i["call_id"] for i in items], [self.call_a])
        # Full-number input is reduced to its suffix before matching the masked digits.
        items = self._items({"phone_number": "+81333334444"})
        self.assertEqual([i["call_id"] for i in items], [self.call_b])
        self.assertEqual(self._items({"phone_number": "9999"}), [])

    def test_date_range_filters(self) -> None:
        self.assertEqual(len(self._items({"from": "2000-01-01"})), 2)
        self.assertEqual(self._items({"from": "2100-01-01"}), [])
        self.assertEqual(self._items({"to": "2000-01-01"}), [])

    def test_state_and_customer_filters(self) -> None:
        pending = self._items({"state": "handoff_pending"})
        self.assertEqual([i["call_id"] for i in pending], [self.call_a])
        by_customer = self._items({"customer_id": "cust_b"})
        self.assertEqual([i["call_id"] for i in by_customer], [self.call_b])

    def test_listing_is_sorted_newest_first(self) -> None:
        items = self._items()
        started = [i["started_at"] for i in items]
        self.assertEqual(started, sorted(started, reverse=True))

    def test_detail_projection_masks_caller_and_carries_trace(self) -> None:
        status, detail = self.service.get_call(ADMIN, self.call_a)
        self.assertEqual(status, 200)
        self.assertNotIn("+81311112222", repr(detail))
        self.assertTrue(detail["caller_phone_number_masked"].endswith("2222"))
        self.assertTrue(detail["transcript"])
        for turn in detail["transcript"]:
            self.assertTrue(turn["turn_id"])
            self.assertIn("speaker", turn)
        self.assertIsNotNone(detail["handoff"])  # insufficient evidence handed off
        self.assertEqual(self.service.get_call(OTHER_TENANT, self.call_a)[0], 404)


if __name__ == "__main__":
    unittest.main()
