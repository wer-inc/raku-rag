"""T081/T082 — Call-center KPI aggregation over persisted calls (022 US5).

Pure aggregation (no I/O): the orchestrator feeds it the tenant's CallSession list (+ QA
evaluations for knowledge-gap topics) and it produces the dashboard summary the contract
defines — call count, AI containment, handoff rate/reasons, unresolved rate, and p95 turn
latencies derived from the per-turn latency maps.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from raku_rag.phone.domain import CallSession, QualityEvaluation

_TERMINAL = {"transferred", "completed", "abandoned", "failed"}
_UNRESOLVED = {"unresolved", "abandoned", "failed"}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _top(counter: Counter, limit: int = 5) -> list[dict]:
    return [
        {"key": key, "count": count}
        for key, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    ]


def aggregate_call_metrics(
    calls: list[CallSession],
    evaluations: list[QualityEvaluation] | None = None,
    *,
    range_from: str | None = None,
    range_to: str | None = None,
) -> dict:
    lower = _parse_iso(range_from)
    upper = _parse_iso(range_to)

    def in_range(call: CallSession) -> bool:
        started = _parse_iso(call.started_at)
        if started is None:
            return True
        if lower and started < lower:
            return False
        if upper and started > upper:
            return False
        return True

    scoped = [c for c in calls if in_range(c)]
    count = len(scoped)
    answered = sum(1 for c in scoped if any(t.speaker == "ai" for t in c.turns))
    handoff_count = sum(1 for c in scoped if c.handoff_required)
    contained = sum(1 for c in scoped if c.state == "completed" and not c.handoff_required)
    unresolved = sum(
        1
        for c in scoped
        if (c.resolution_status in _UNRESOLVED) or (c.state in {"abandoned", "failed"})
    )
    completed_terminal = sum(1 for c in scoped if c.state in _TERMINAL)

    handoff_reasons: Counter = Counter()
    intents: Counter = Counter()
    durations: list[float] = []
    latency_totals: list[float] = []
    latency_rag: list[float] = []
    for call in scoped:
        if call.handoff_reason:
            handoff_reasons[call.handoff_reason] += 1
        if call.intent:
            intents[call.intent] += 1
        started = _parse_iso(call.started_at)
        ended = _parse_iso(call.ended_at)
        if started and ended and ended >= started:
            durations.append((ended - started).total_seconds())
        for turn in call.turns:
            if turn.speaker != "ai":
                continue
            total = turn.latency_ms.get("total")
            rag = turn.latency_ms.get("rag")
            if isinstance(total, (int, float)):
                latency_totals.append(float(total))
            if isinstance(rag, (int, float)):
                latency_rag.append(float(rag))

    gap_topics: Counter = Counter()
    for evaluation in evaluations or []:
        for topic in evaluation.knowledge_gap_topics:
            gap_topics[topic] += 1

    def rate(numerator: int) -> float:
        return round(numerator / count, 4) if count else 0.0

    return {
        "summary": {
            "call_count": count,
            "answered_count": answered,
            "answer_rate": rate(answered),
            "ai_containment_rate": rate(contained),
            "handoff_rate": rate(handoff_count),
            "unresolved_rate": rate(unresolved),
            "terminal_count": completed_terminal,
            "average_handle_time_seconds": (
                round(sum(durations) / len(durations), 1) if durations else 0.0
            ),
            "p95_total_turn_latency_ms": _p95(latency_totals),
            "p95_rag_latency_ms": _p95(latency_rag),
        },
        "top_handoff_reasons": _top(handoff_reasons),
        "top_intents": _top(intents),
        "knowledge_gap_topics": _top(gap_topics),
    }
