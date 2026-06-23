"""P2-1 / AF-6 regression gate — the DEPLOYED manufacturing answer route must audit.

The in-memory behavioural guarantee (``ManufacturingSystem.answer`` records the high-risk
classification + safety decision + citation access into the tamper-evident hash-chain audit) is pinned
by ``tests/manufacturing/test_audit_coverage.py``. What this file pins is the *wiring*: that the
deployed ``apps/answer-service/server.py`` ``/internal/manufacturing/answer`` handler actually routes
through that audited path (``manufacturing_system.answer``) and NOT the audit-less overlay
(``build_manufacturing_answer_service(...).answer`` discarding the decision with ``*_``).

This is the exact gap AF-6 closed: previously the deployed safety-gate answer wrote NO audit row even
though the drafts/approval routes did. Stdlib-only, Tier-A fast — guards against a silent revert.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _answer_handler_block(src: str) -> str:
    """Return the source of the ``/internal/manufacturing/answer`` elif branch only."""
    start = src.index('elif path == "/internal/manufacturing/answer":')
    # the branch ends at the next sibling `elif` at the same indentation
    rest = src[start + 1 :]
    m = re.search(r"\n {16}elif ", rest)
    end = start + 1 + (m.start() if m else len(rest))
    return src[start:end]


class ManufacturingAnswerRouteAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.src = (ROOT / "apps/answer-service/server.py").read_text(encoding="utf-8")
        self.block = _answer_handler_block(self.src)
        # assert on executable code only — comment lines (which name the old overlay for context)
        # must not trip the negative checks.
        self.code = "\n".join(
            ln for ln in self.block.splitlines() if not ln.lstrip().startswith("#")
        )

    def test_answer_route_uses_the_audited_system_answer(self) -> None:
        # routes through the manufacturing_system (PostgresManufacturingAuditLogWriter is wired here)
        self.assertIn("manufacturing_system.answer(", self.code)

    def test_answer_route_does_not_use_the_audit_less_overlay(self) -> None:
        # the audit-less overlay discarded the safety decision (`mfg_ans, *_ = service.answer(...)`)
        self.assertNotIn("build_manufacturing_answer_service", self.code)
        self.assertNotIn("mfg_ans, *_", self.code)

    def test_audit_less_overlay_symbol_is_not_imported(self) -> None:
        # the symbol must no longer be imported anywhere in the deployed answer-service
        self.assertNotIn(
            "from raku_rag.manufacturing.wiring import",
            self.src,
        )

    def test_answer_route_forwards_the_collection_for_audit_scoping(self) -> None:
        # FR-MFG-030 collection axis must reach the audited answer (collection_id passed through)
        self.assertIn("collection_id", self.block)


if __name__ == "__main__":
    unittest.main()
