"""ADR-018 A8 §12.1 — the /internal/reviews/extraction endpoint surfaces the quarantine queue."""

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
from tests.manufacturing.unit.test_durable_manufacturing_wiring import _FakeConnection

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_rev"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server_reviews", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TestReviewsEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        srv = _load_server()
        self.system = MvpSystem()
        self.system._conn = _FakeConnection()
        self.system.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.system.ingest_text(
            tenant_id=T, collection_id="c", document_id="good", text="Pump P-12 interval 90 days."
        )
        self.system.ingest_text(
            tenant_id=T, collection_id="c", document_id="broken", text="Pump P-12 " + "�" * 40
        )
        self.httpd = HTTPServer(("127.0.0.1", 0), srv.make_handler(self.system))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()

    def _get(self, path: str) -> dict:
        headers = {
            "x-raku-tenant-id": T,
            "x-raku-user-id": "admin",
            "x-raku-groups": json.dumps(["ops"]),
            "x-raku-roles": json.dumps(["admin"]),
        }
        request = Request(f"{self.base}{path}", headers=headers, method="GET")
        with urlopen(request, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_review_queue_lists_only_quarantined_docs(self) -> None:
        payload = self._get("/internal/reviews/extraction")
        docs = {item["document_id"] for item in payload["items"]}
        self.assertIn("broken", docs)
        self.assertNotIn("good", docs)
        for item in payload["items"]:
            self.assertEqual(item["status"], "review_required")
            self.assertTrue(item["reasons"])


if __name__ == "__main__":
    unittest.main()
