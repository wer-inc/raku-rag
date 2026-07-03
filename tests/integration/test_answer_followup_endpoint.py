"""U19 — `/internal/manufacturing/answer` `history` support on the deployed HTTP boundary.

Boots the REAL `make_handler` stack in-process (governance-endpoint pattern) and proves the wire
contract end-to-end: the optional `history` field is accepted, a referential follow-up is resolved
against it (right citation), the response reports `context_carried` + `retrieval_query` for the UI
chip (文脈を引き継ぎました), a dangerous follow-up still blocks from its RAW text over the wire, and
requests without history (or with a non-referential query) carry no new fields and behave as today.
The pure resolution logic and the full safety matrix live in
tests/unit/test_answer_followup_context.py; this file pins the HTTP plumbing.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from raku_rag.app import MvpSystem
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import ApprovalStatus
from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY
from tests.manufacturing.helpers import mfg_meta
from tests.manufacturing.unit.test_durable_manufacturing_wiring import _FakeConnection

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_mfg_followup"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TestAnswerFollowupEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        srv = _load_server()
        system = MvpSystem()
        system._conn = _FakeConnection()
        # Benign corpus ("manuals"): two equipment docs with DIFFERENT torque values, so answering
        # from the WRONG document is observable, not just "answered at all".
        cls._ingest(
            system,
            "manuals",
            "eq-p101",
            "P-101の点検手順は電源停止、外観確認、記録の順です。締付トルクは25N・mです。",
            ApprovalStatus.APPROVED,
        )
        cls._ingest(
            system,
            "manuals",
            "eq-p203",
            "P-203の点検手順は加圧停止、清掃、記録の順です。締付トルクは60N・mです。",
            ApprovalStatus.APPROVED,
        )
        # Danger corpus ("safety", separate collection so the scenarios cannot cross-talk): an
        # APPROVED but unrelated context doc + the genuinely on-topic doc still PENDING_REVIEW —
        # the ChatbotL2CoreferenceHighRiskSafetyTest shape, replayed over this HTTP boundary.
        cls._ingest(
            system,
            "safety",
            "routine-inspection-schedule",
            "Routine inspection of the equipment is performed every 30 days by the maintenance team.",
            ApprovalStatus.APPROVED,
        )
        cls._ingest(
            system,
            "safety",
            "accumulator-pressure-release-pending",
            "蓄圧器の圧力を抜く際は、手動排出弁をゆっくり開いてから配管を開放してください。",
            ApprovalStatus.PENDING_REVIEW,
            effective_date=None,
        )
        for collection in ("manuals", "safety"):
            system.grant(T, ScopeType.COLLECTION, collection, SubjectType.USER, "alice")
        cls.httpd = HTTPServer(("127.0.0.1", 0), srv.make_handler(system))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        cls.httpd.server_close()

    @staticmethod
    def _ingest(system, collection_id, document_id, text, status, effective_date="2026-01-01"):
        system.ingest_text(
            tenant_id=T, collection_id=collection_id, document_id=document_id, text=text
        )
        system.registry.get(T, document_id).metadata[MFG_META_KEY] = mfg_meta(
            tenant_id=T,
            document_id=document_id,
            approval_status=status,
            effective_date=effective_date,
        )

    def _answer(self, body: dict) -> dict:
        payload = {"tenant_id": T, "user_id": "alice", "groups": [], "roles": [], **body}
        request = Request(
            f"{self.base}/internal/manufacturing/answer",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    BENIGN_HISTORY = [{"question": "P-101 の点検手順を教えて", "cited_document_ids": ["eq-p101"]}]

    def test_referential_followup_with_history_answers_the_right_document(self):
        out = self._answer(
            {
                "query": "その締付トルクは?",
                "collection_id": "manuals",
                "history": self.BENIGN_HISTORY,
            }
        )

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["citations"][0]["document_id"], "eq-p101")
        self.assertIn("25N・m", out["text"])
        self.assertNotIn("60N・m", out["text"])
        # Transparency fields for the UI chip.
        self.assertIs(out["context_carried"], True)
        self.assertIn("その締付トルクは?", out["retrieval_query"])
        self.assertIn("p-101", out["retrieval_query"].casefold())

    def test_same_followup_without_history_reports_no_carry_and_misses_the_equipment(self):
        out = self._answer({"query": "その締付トルクは?", "collection_id": "manuals"})

        self.assertNotIn("context_carried", out)
        self.assertNotIn("retrieval_query", out)
        # The "before" behavior U19 closes: no carried identifier => the other equipment's value.
        self.assertNotIn("25N・m", out.get("text") or "")

    def test_non_referential_query_with_history_is_untouched(self):
        out = self._answer(
            {
                "query": "P-203 の点検手順を教えて",
                "collection_id": "manuals",
                "history": self.BENIGN_HISTORY,
            }
        )

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["citations"][0]["document_id"], "eq-p203")
        self.assertNotIn("context_carried", out)
        self.assertNotIn("retrieval_query", out)

    def test_dangerous_followup_still_blocks_from_the_raw_text_over_the_wire(self):
        out = self._answer(
            {
                "query": "その圧力の抜き方を教えて",
                "collection_id": "safety",
                "history": [
                    {
                        "question": "How often is routine equipment inspection performed?",
                        "cited_document_ids": ["routine-inspection-schedule"],
                    }
                ],
            }
        )

        self.assertEqual(out["status"], "insufficient_evidence")
        self.assertTrue(out["manufacturing"]["high_risk"])
        self.assertEqual(out["manufacturing"]["safety_block_reason"], "approved_citation_missing")
        self.assertIsNone(out["text"])
        self.assertEqual(out["citations"], [])
        # The rewrite itself is reported transparently even when the answer is blocked.
        self.assertIs(out["context_carried"], True)


if __name__ == "__main__":
    unittest.main()
