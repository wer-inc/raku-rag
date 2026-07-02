"""T078 — Call KPI aggregation (022 US5)."""

from __future__ import annotations

import unittest

from raku_rag.phone.domain import CallSession, ConversationTurn, QualityEvaluation
from raku_rag.phone.metrics import aggregate_call_metrics


def _call(
    call_id: str,
    *,
    state: str,
    handoff: bool = False,
    reason: str | None = None,
    intent: str | None = None,
    started: str = "2026-07-02T10:00:00Z",
    ended: str | None = "2026-07-02T10:03:00Z",
    totals: tuple[float, ...] = (),
) -> CallSession:
    call = CallSession(tenant_id="t", call_id=call_id, correlation_id=f"corr_{call_id}")
    call.state = state
    call.handoff_required = handoff
    call.handoff_reason = reason
    call.intent = intent
    call.started_at = started
    call.ended_at = ended
    if state in {"abandoned", "failed"}:
        call.resolution_status = state
    elif state == "transferred":
        call.resolution_status = "transferred"
    elif state == "completed":
        call.resolution_status = "resolved"
    for index, total in enumerate(totals, start=1):
        call.turns.append(
            ConversationTurn(
                tenant_id="t",
                call_id=call_id,
                turn_id=f"turn_{index}",
                sequence_no=index,
                speaker="ai",
                event_type="speech",
                latency_ms={"total": total, "rag": total / 2},
            )
        )
    return call


class TestAggregateCallMetrics(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = [
            _call("c1", state="completed", intent="business_hours", totals=(100.0, 200.0)),
            _call(
                "c2",
                state="transferred",
                handoff=True,
                reason="customer_requested_human",
                intent="pricing_plan",
                totals=(150.0,),
            ),
            _call(
                "c3",
                state="transferred",
                handoff=True,
                reason="insufficient_evidence",
                intent="pricing_plan",
                totals=(300.0,),
            ),
            _call("c4", state="abandoned", intent="faq", ended="2026-07-02T10:00:30Z"),
        ]

    def test_summary_rates(self) -> None:
        result = aggregate_call_metrics(self.calls)
        summary = result["summary"]
        self.assertEqual(summary["call_count"], 4)
        self.assertEqual(summary["answered_count"], 3)  # c4 has no AI turn
        self.assertEqual(summary["ai_containment_rate"], 0.25)  # only c1
        self.assertEqual(summary["handoff_rate"], 0.5)
        self.assertEqual(summary["unresolved_rate"], 0.25)  # c4 abandoned
        self.assertAlmostEqual(summary["average_handle_time_seconds"], 142.5, places=1)
        self.assertEqual(summary["p95_total_turn_latency_ms"], 300.0)

    def test_top_breakdowns(self) -> None:
        result = aggregate_call_metrics(self.calls)
        reasons = {item["key"]: item["count"] for item in result["top_handoff_reasons"]}
        self.assertEqual(reasons["customer_requested_human"], 1)
        self.assertEqual(reasons["insufficient_evidence"], 1)
        intents = {item["key"]: item["count"] for item in result["top_intents"]}
        self.assertEqual(intents["pricing_plan"], 2)

    def test_knowledge_gap_topics_from_evaluations(self) -> None:
        evaluations = [
            QualityEvaluation(
                tenant_id="t",
                evaluation_id="e1",
                call_id="c3",
                reviewer_id="qa",
                knowledge_gap_topics=["返金条件", "保証範囲"],
            ),
            QualityEvaluation(
                tenant_id="t",
                evaluation_id="e2",
                call_id="c2",
                reviewer_id="qa",
                knowledge_gap_topics=["返金条件"],
            ),
        ]
        result = aggregate_call_metrics(self.calls, evaluations)
        topics = {item["key"]: item["count"] for item in result["knowledge_gap_topics"]}
        self.assertEqual(topics["返金条件"], 2)
        self.assertEqual(topics["保証範囲"], 1)

    def test_date_range_filter(self) -> None:
        result = aggregate_call_metrics(
            self.calls, range_from="2026-07-02T09:00:00Z", range_to="2026-07-02T11:00:00Z"
        )
        self.assertEqual(result["summary"]["call_count"], 4)
        result = aggregate_call_metrics(self.calls, range_from="2026-07-03T00:00:00Z")
        self.assertEqual(result["summary"]["call_count"], 0)

    def test_empty_is_zero_safe(self) -> None:
        result = aggregate_call_metrics([])
        self.assertEqual(result["summary"]["call_count"], 0)
        self.assertEqual(result["summary"]["handoff_rate"], 0.0)
        self.assertIsNone(result["summary"]["p95_total_turn_latency_ms"])


if __name__ == "__main__":
    unittest.main()
