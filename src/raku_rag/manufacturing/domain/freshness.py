"""★G4 — document freshness: derived review-overdue computation (goal.md §1-4).

A document carries three OPTIONAL lifecycle fields on ``ManufacturingDocumentMetadata``
(``owner`` / ``review_cycle_days`` / ``last_verified_at``, migration 0024). Staleness is always
DERIVED here, never stored:

    review_overdue  <=>  last_verified_at + review_cycle_days < today

and ONLY when both fields are set (``review_cycle_days > 0`` and ``last_verified_at`` parses as an
ISO date). A document with no cycle configured is never overdue — freshness tracking is opt-in per
document, so legacy metadata (which lacks the fields entirely) keeps its exact previous behaviour.
An unparseable date also yields "not overdue" (fail-open by design: this signal drives a review
NUDGE, not the safety gate — approval/effective/obsolete state remains the safety boundary).

Canonical / latest-version selection across sibling documents is OUT OF SCOPE here (deferred; see
docs/product/goal-gap-audit.md ★G4).

stdlib only. Pure functions — ``today`` is always injected by the caller (or defaulted once at the
API edge), keeping the computation deterministic for tests.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

__all__ = ["review_due_date", "is_review_overdue", "review_overdue_entries"]


def review_due_date(last_verified_at: str, review_cycle_days: int) -> date | None:
    """The date the next human verification is due, or None when no cycle applies.

    ``last_verified_at`` accepts an ISO date or timestamp (only the date part is used).
    Returns None unless BOTH fields are set and valid.
    """
    if not last_verified_at or review_cycle_days is None or int(review_cycle_days) <= 0:
        return None
    try:
        verified = date.fromisoformat(str(last_verified_at)[:10])
    except ValueError:
        return None
    return verified + timedelta(days=int(review_cycle_days))


def _get(meta, key: str, default):
    """Field accessor working over the metadata dataclass AND its ``to_mapping()`` dict form."""
    if isinstance(meta, dict):
        return meta.get(key, default)
    return getattr(meta, key, default)


def is_review_overdue(meta, *, today: date) -> bool:
    """True when ``meta``'s review window has lapsed (due date strictly before ``today``).

    Duck-typed over anything carrying ``last_verified_at`` / ``review_cycle_days`` (the metadata
    dataclass or its ``to_mapping()`` dict), so both the in-memory and the Postgres-jsonb
    round-tripped forms work.
    """
    cycle = _get(meta, "review_cycle_days", 0) or 0
    try:
        cycle = int(cycle)
    except (TypeError, ValueError):
        return False
    due = review_due_date(str(_get(meta, "last_verified_at", "") or ""), cycle)
    return due is not None and due < today


def review_overdue_entries(metas: Iterable, *, today: date) -> tuple[dict, ...]:
    """Reference-only rows for every overdue metadata in ``metas``, sorted most-overdue first.

    Each entry: ``{document_id, owner, last_verified_at, review_due_date}`` (IDs / dates only —
    never document content), the shape surfaced by the dashboard / KPI views.
    """
    rows: list[tuple[date, dict]] = []
    for meta in metas:
        if meta is None or not is_review_overdue(meta, today=today):
            continue
        due = review_due_date(
            str(_get(meta, "last_verified_at", "") or ""),
            int(_get(meta, "review_cycle_days", 0) or 0),
        )
        if due is None:  # pragma: no cover - is_review_overdue already guarantees a due date
            continue
        rows.append(
            (
                due,
                {
                    "document_id": str(_get(meta, "document_id", "") or ""),
                    "owner": str(_get(meta, "owner", "") or ""),
                    "last_verified_at": str(_get(meta, "last_verified_at", "") or ""),
                    "review_due_date": due.isoformat(),
                },
            )
        )
    rows.sort(key=lambda r: (r[0], r[1]["document_id"]))
    return tuple(entry for _due, entry in rows)
