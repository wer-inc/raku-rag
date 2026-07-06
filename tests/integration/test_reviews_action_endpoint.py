"""ADR-018 §12.2 — POST /internal/reviews/extraction/actions applies a reviewer decision."""

from __future__ import annotations

import importlib.util
import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from raku_rag.app import MvpSystem
from raku_rag.domain.models import ScopeType, SubjectType
from tests.manufacturing.unit.test_durable_manufacturing_wiring import _FakeConnection

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_rev_ep"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server_rev_actions", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TestReviewActionEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        srv = _load_server()
        self.system = MvpSystem()
        self.system._conn = _FakeConnection()
        self.system.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.system.ingest_text(
            tenant_id=T, collection_id="c", document_id="broken", text="X " + "�" * 40
        )
        self.cid = self.system.list_extraction_reviews(T)[0]["chunk_id"]
        self.httpd = HTTPServer(("127.0.0.1", 0), srv.make_handler(self.system))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()

    def _post(self, body: dict):
        headers = {
            "x-raku-tenant-id": T,
            "x-raku-user-id": "reviewer1",
            "x-raku-groups": json.dumps(["ops"]),
            "x-raku-roles": json.dumps(["admin"]),
            "content-type": "application/json",
        }
        req = Request(
            f"{self.base}/internal/reviews/extraction/actions",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_approve_via_endpoint(self) -> None:
        status, payload = self._post({"chunk_id": self.cid, "action": "approve"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "manual_approved")
        self.assertEqual(payload["reviewed_by"], "reviewer1")
        self.assertEqual(self.system.list_extraction_reviews(T), [])

    def test_unknown_action_is_400(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            self._post({"chunk_id": self.cid, "action": "bogus"})
        self.assertEqual(ctx.exception.code, 400)

    def test_missing_chunk_is_404(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            self._post({"chunk_id": "nope", "action": "approve"})
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
