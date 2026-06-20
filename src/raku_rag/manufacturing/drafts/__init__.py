"""US4 draft generation + review workflow (FR-MFG-010/010a/010b, Hard Rule 1).

Reuses the Phase-2 schemas (``raku_rag.manufacturing.domain.draft``) + interfaces
(``raku_rag.manufacturing.interfaces.DraftGenerator`` / ``ReviewWorkflow``) + US1 SafetyGate. AI output
is ALWAYS ``status=draft`` and is only ever ``approved`` via an explicit reviewer action (SC-MFG-007).
"""

from __future__ import annotations

from raku_rag.manufacturing.drafts.generator import DraftGenerator, coerce_kind
from raku_rag.manufacturing.drafts.review import ReviewWorkflow

__all__ = ["DraftGenerator", "ReviewWorkflow", "coerce_kind"]
