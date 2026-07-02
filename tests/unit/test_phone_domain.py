"""T008 — Call / turn / scenario domain invariants (022 data-model.md)."""

from __future__ import annotations

import unittest

from raku_rag.phone.domain import (
    CallSession,
    HandoffPackage,
    PhoneCitationRef,
    ScenarioVersion,
    InvalidCallTransition,
    InvalidScenarioTransition,
    TERMINAL_CALL_STATES,
    assert_call_transition,
    assert_scenario_transition,
)


def _call(**kwargs) -> CallSession:
    defaults = dict(tenant_id="tenant_a", call_id="call_1", correlation_id="corr_1")
    defaults.update(kwargs)
    return CallSession(**defaults)


class TestCallStateMachine(unittest.TestCase):
    def test_happy_path_answer_and_complete(self) -> None:
        call = _call()
        call.transition("active")
        call.transition("completed")
        self.assertEqual(call.state, "completed")
        self.assertIsNotNone(call.ended_at)
        self.assertEqual(call.resolution_status, "resolved")

    def test_handoff_path_sets_transferred_resolution(self) -> None:
        call = _call()
        call.transition("active")
        call.transition("handoff_pending")
        call.transition("transferred")
        self.assertEqual(call.resolution_status, "transferred")
        self.assertTrue(call.is_terminal())

    def test_hold_resume(self) -> None:
        call = _call()
        call.transition("active")
        call.transition("on_hold")
        call.transition("active")
        self.assertEqual(call.state, "active")

    def test_terminal_states_reject_further_transitions(self) -> None:
        for terminal in TERMINAL_CALL_STATES:
            with self.subTest(terminal=terminal):
                with self.assertRaises(InvalidCallTransition):
                    assert_call_transition(terminal, "active")

    def test_ringing_cannot_jump_to_handoff_pending(self) -> None:
        with self.assertRaises(InvalidCallTransition):
            assert_call_transition("ringing", "handoff_pending")

    def test_sequence_no_is_monotonic(self) -> None:
        call = _call()
        self.assertEqual(call.next_sequence_no(), 1)


class TestScenarioLifecycle(unittest.TestCase):
    def test_draft_cannot_publish_directly(self) -> None:
        with self.assertRaises(InvalidScenarioTransition):
            assert_scenario_transition("draft", "published")

    def test_full_lifecycle_transitions(self) -> None:
        assert_scenario_transition("draft", "in_review")
        assert_scenario_transition("in_review", "approved")
        assert_scenario_transition("approved", "published")
        assert_scenario_transition("approved", "scheduled")
        assert_scenario_transition("scheduled", "published")
        assert_scenario_transition("published", "archived")

    def test_published_version_is_immutable(self) -> None:
        version = ScenarioVersion(
            tenant_id="tenant_a",
            scenario_id="faq-basic",
            scenario_version_id="scv_1",
            version_number=1,
            status="published",
        )
        self.assertTrue(version.is_immutable())
        with self.assertRaises(InvalidScenarioTransition):
            assert_scenario_transition("published", "draft")


class TestTraceabilityShapes(unittest.TestCase):
    def test_citation_ref_carries_trace_identifiers(self) -> None:
        ref = PhoneCitationRef(
            source_id="faq",
            document_id="FAQ-HOURS",
            chunk_id="chunk_1",
            version="3",
            retrieval_score=0.91,
            approval_status="approved",
        )
        payload = ref.public()
        for key in ("source_id", "document_id", "chunk_id", "version", "retrieval_score"):
            self.assertIn(key, payload)
        self.assertEqual(payload["approval_status"], "approved")

    def test_handoff_package_exposes_only_masked_number(self) -> None:
        package = HandoffPackage(
            tenant_id="tenant_a",
            handoff_package_id="handoff_1",
            call_id="call_1",
            reason="customer_requested_human",
            caller_phone_number_masked="+81******1234",
        )
        payload = package.public()
        self.assertEqual(payload["customer"]["phone_number_masked"], "+81******1234")
        self.assertNotIn("caller_phone_number", payload)

    def test_call_summary_item_uses_masked_number(self) -> None:
        call = _call(caller_phone_number_masked="+81******1234")
        item = call.summary_item()
        self.assertEqual(item["caller_phone_number_masked"], "+81******1234")


if __name__ == "__main__":
    unittest.main()
