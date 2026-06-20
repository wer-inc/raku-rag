"""T021 — Manufacturing answer/search API surface (overlay on the 001 result, non-breaking).

This package wires the manufacturing safety overlay onto the reused 001 answer/search path and
exposes an in-memory composition (``raku_rag.manufacturing.app.ManufacturingSystem``) that mirrors
``raku_rag.app.MvpSystem`` so tests can drive it directly. The result types ADD manufacturing fields
to the 001 result without changing 001 field meaning (additive; contracts §A).

Public surface:
  - ``ManufacturingAnswerService`` / ``ManufacturingAnswer`` / ``ManufacturingCitation`` (answer_ext)
  - ``ManufacturingSearchService`` / ``ManufacturingSearchResult`` (search_ext)
  - ``record_answer_decision`` (audit, FR-MFG-021)
"""

from __future__ import annotations

from raku_rag.manufacturing.api.answer_ext import (
    ManufacturingAnswer,
    ManufacturingAnswerService,
    ManufacturingCitation,
)
from raku_rag.manufacturing.api.audit import record_answer_decision, record_answer_feedback
from raku_rag.manufacturing.api.ingest_metadata import ManufacturingSyncStatusService
from raku_rag.manufacturing.api.search_ext import (
    ManufacturingSearchResult,
    ManufacturingSearchService,
)

__all__ = [
    "ManufacturingAnswer",
    "ManufacturingAnswerService",
    "ManufacturingCitation",
    "ManufacturingSyncStatusService",
    "ManufacturingSearchResult",
    "ManufacturingSearchService",
    "record_answer_decision",
    "record_answer_feedback",
]
