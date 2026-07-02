"""監査エビデンスパック — the audit hash chain rendered as a compliance artifact.

Aggregates the tenant's tamper-evident audit chain into the monthly report a quality-assurance /
safety office can file as-is (ISO9001 internal audits, 安全衛生委員会): how many questions were
asked, how many answers carried approved evidence, what was BLOCKED and why, which calls were
handed to humans, who viewed transcripts, and whether the hash chain itself still verifies.
Reference IDs only — the pack never contains transcript or answer text (same rule as the audit
entries it summarizes).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from raku_rag.domain.models import IdentityClaims

# Actions counted as "the AI answered (or declined) a question" across all three channels —
# the workspace/chat/phone layers all record through the same manufacturing audit writer.
_ANSWER_ACTION = "answer"
_GROUNDED_DECISIONS = frozenset({"ok"})
_BLOCKED_DECISION_PREFIXES = ("blocked", "insufficient", "temporarily_unavailable")
_ACCESS_ACTIONS = frozenset(
    {"phone.transcript_viewed", "phone.handoff_viewed", "phone.qa_reviews_viewed"}
)
_LIFECYCLE_ACTIONS = frozenset({"phone.export_requested", "phone.delete_request"})
_QA_ACTION = "phone.quality_evaluated"
_HANDOFF_HINT = "handoff"


def _in_range(timestamp: str, from_iso: str, to_iso: str) -> bool:
    if not timestamp:
        return False
    if from_iso and timestamp < from_iso:
        return False
    if to_iso and timestamp > to_iso:
        return False
    return True


def build_evidence_pack(
    audit,
    principal: IdentityClaims,
    *,
    from_iso: str = "",
    to_iso: str = "",
) -> dict:
    """Aggregate the tenant's audit chain into the compliance evidence pack (reference IDs only)."""

    entries = list(audit.read_all(principal))
    period_entries = [e for e in entries if _in_range(str(e.timestamp or ""), from_iso, to_iso)]

    answers = [e for e in period_entries if e.action == _ANSWER_ACTION]
    decisions = Counter(str(e.decision or "unknown") for e in answers)
    grounded = sum(count for d, count in decisions.items() if d in _GROUNDED_DECISIONS)
    blocked = {
        d: c
        for d, c in decisions.items()
        if any(d.startswith(p) for p in _BLOCKED_DECISION_PREFIXES)
    }

    handoffs = [
        {
            "timestamp": str(e.timestamp or ""),
            "action": e.action,
            "resource_id": e.resource_id,
            "reason": str(e.decision or e.reason or ""),
        }
        for e in period_entries
        if _HANDOFF_HINT in str(e.action or "") or _HANDOFF_HINT in str(e.decision or "")
    ]

    qa_entries = [e for e in period_entries if e.action == _QA_ACTION]
    qa_flags = Counter()
    for e in qa_entries:
        reason = str(e.decision or "")
        if reason and reason != "reviewed":
            qa_flags[reason] += 1

    access_counts = Counter(e.action for e in period_entries if e.action in _ACCESS_ACTIONS)
    lifecycle = [
        {
            "timestamp": str(e.timestamp or ""),
            "action": e.action,
            "resource_id": e.resource_id,
            "decision": str(e.decision or ""),
            "actor_id": e.actor_id,
        }
        for e in period_entries
        if e.action in _LIFECYCLE_ACTIONS
    ]

    chain_verified = bool(audit.verify_chain(principal))
    return {
        "tenant_id": principal.tenant_id,
        "period": {"from": from_iso or None, "to": to_iso or None},
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "audit_entry_count": len(period_entries),
            "question_count": len(answers),
            "grounded_answer_count": grounded,
            "grounded_answer_rate": (grounded / len(answers)) if answers else None,
            "blocked_count": sum(blocked.values()),
            "handoff_count": len(handoffs),
            "qa_review_count": len(qa_entries),
        },
        "answer_decisions": dict(sorted(decisions.items())),
        "blocked_by_reason": dict(sorted(blocked.items())),
        "handoffs": handoffs[:200],
        "qa_flags": dict(sorted(qa_flags.items())),
        "access_transparency": dict(sorted(access_counts.items())),
        "data_lifecycle_events": lifecycle[:100],
        "hash_chain": {
            "verified": chain_verified,
            "total_entries": len(entries),
            "first_entry_at": str(entries[0].timestamp) if entries else None,
            "last_entry_at": str(entries[-1].timestamp) if entries else None,
        },
    }
