"""T039 — Handoff trigger rules and outcome transitions (US2)."""

from __future__ import annotations

import unittest

from raku_rag.phone.domain import CallSession, HandoffPackage, PhoneCitationRef
from raku_rag.phone.handoff import (
    HandoffRules,
    HandoffService,
    destination_for,
    detect_high_risk,
    detect_human_request,
    detect_sentiment,
    priority_for,
)
from raku_rag.phone.interfaces import HandoffDispatchResult


def _call(**kwargs) -> CallSession:
    defaults = dict(
        tenant_id="tenant_a",
        call_id="call_1",
        correlation_id="corr_1",
        caller_phone_number_masked="+81******1234",
        customer_id="cust_1",
    )
    defaults.update(kwargs)
    call = CallSession(**defaults)
    call.transition("active")
    return call


class TestTriggerDetection(unittest.TestCase):
    def test_customer_requested_human_variants(self) -> None:
        for text in ("人につないでください", "オペレーターに代わって", "担当者お願いします", "human please"):
            with self.subTest(text=text):
                self.assertTrue(detect_human_request(text))
        self.assertFalse(detect_human_request("営業時間を教えて"))

    def test_high_risk_terms(self) -> None:
        for text in ("返金を確約できますか", "訴訟を検討しています", "損害賠償を請求します"):
            with self.subTest(text=text):
                self.assertTrue(detect_high_risk(text))
        self.assertFalse(detect_high_risk("料金プランを教えて"))

    def test_negative_sentiment(self) -> None:
        self.assertEqual(detect_sentiment("いい加減にしてください。最悪です"), "angry")
        self.assertEqual(detect_sentiment("ありがとうございます"), "neutral")


class TestPreRagRules(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = HandoffRules()

    def test_customer_request_is_unconditional(self) -> None:
        call = _call()
        reason = self.rules.pre_rag_reason(call, "人につないで", 0.99, set())
        self.assertEqual(reason, "customer_requested_human")
        # Even when the scenario only whitelists other reasons, the request still transfers.
        reason = self.rules.pre_rag_reason(call, "人につないで", 0.99, {"insufficient_evidence"})
        self.assertEqual(reason, "customer_requested_human")

    def test_high_risk_intent(self) -> None:
        call = _call()
        self.assertEqual(
            self.rules.pre_rag_reason(call, "返金を確約してください", 0.99, set()),
            "high_risk_intent",
        )

    def test_negative_sentiment(self) -> None:
        call = _call()
        self.assertEqual(
            self.rules.pre_rag_reason(call, "ふざけるな、最悪だ", 0.99, set()),
            "negative_sentiment",
        )

    def test_low_confidence_requires_retries_first(self) -> None:
        call = _call()
        call.low_confidence_count = 1
        self.assertIsNone(self.rules.pre_rag_reason(call, "えー", 0.2, set()))
        call.low_confidence_count = 2
        self.assertEqual(
            self.rules.pre_rag_reason(call, "えー", 0.2, set()), "low_asr_confidence"
        )

    def test_repeated_misunderstanding(self) -> None:
        call = _call()
        call.clarification_count = 3
        self.assertEqual(
            self.rules.pre_rag_reason(call, "それで", 0.99, set()),
            "repeated_misunderstanding",
        )


class TestDestinationAndPriority(unittest.TestCase):
    def test_priority_by_reason(self) -> None:
        self.assertEqual(priority_for("high_risk_intent"), "high")
        self.assertEqual(priority_for("customer_requested_human"), "normal")

    def test_destination_by_intent(self) -> None:
        self.assertEqual(destination_for("insufficient_evidence", "refund_cancellation")[1], "billing-support")
        self.assertEqual(destination_for("insufficient_evidence", "complaint")[1], "escalation")
        self.assertEqual(destination_for("insufficient_evidence", None)[1], "general-support")


class TestPackageCreation(unittest.TestCase):
    def test_package_contains_required_context(self) -> None:
        call = _call(intent="pricing_plan")
        call.collected_slots["contract_id"] = "C-123"
        service = HandoffService()
        citations = (
            PhoneCitationRef(source_id="faq", document_id="FAQ-PRICING", chunk_id="c1"),
        )
        package = service.create_package(
            call, reason="insufficient_evidence", sentiment="neutral", citations=citations
        )
        self.assertEqual(package.status, "queued")
        self.assertEqual(package.reason, "insufficient_evidence")
        self.assertEqual(package.confirmed_slots["contract_id"], "C-123")
        self.assertEqual(package.citations[0].document_id, "FAQ-PRICING")
        self.assertEqual(package.caller_phone_number_masked, "+81******1234")
        self.assertTrue(package.recommended_next_action)
        self.assertTrue(call.handoff_required)
        self.assertEqual(call.handoff_package_id, package.handoff_package_id)

    def test_dispatch_failure_falls_back_to_callback(self) -> None:
        class FailingProvider:
            name = "failing"

            def dispatch(self, package: HandoffPackage) -> HandoffDispatchResult:
                return HandoffDispatchResult(status="failed", failure_reason="queue down")

        service = HandoffService(provider=FailingProvider())
        package = service.create_package(_call(), reason="customer_requested_human")
        # FR-030: live transfer failed -> configured fallback outcome, never a dead end.
        self.assertEqual(package.status, "callback_requested")
        self.assertEqual(package.failure_reason, "queue down")

    def test_dispatch_exception_is_contained(self) -> None:
        class ExplodingProvider:
            name = "exploding"

            def dispatch(self, package: HandoffPackage) -> HandoffDispatchResult:
                raise RuntimeError("boom")

        service = HandoffService(provider=ExplodingProvider())
        package = service.create_package(_call(), reason="customer_requested_human")
        self.assertEqual(package.status, "callback_requested")

    def test_accept_transition(self) -> None:
        service = HandoffService()
        package = service.create_package(_call(), reason="customer_requested_human")
        service.accept(package, operator_id="op_1", queue_id="billing-support")
        self.assertEqual(package.status, "accepted")
        self.assertEqual(package.operator_id, "op_1")
        self.assertEqual(package.destination_id, "billing-support")
        self.assertIsNotNone(package.accepted_at)


if __name__ == "__main__":
    unittest.main()
