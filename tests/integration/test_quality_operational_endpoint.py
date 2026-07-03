"""★G3b/★G5 — GET /internal/quality/operational on the answer-service boundary.

Verifies the endpoint wiring in the deterministic profile: the tenant comes from the
authenticated principal headers ONLY (never a query param), the summary reflects real answer
traffic recorded by the shared MetricsRecorder, and low_rating_count comes from the persisted
feedback repository.
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
from tests.helpers import claims
from tests.manufacturing.unit.test_durable_manufacturing_wiring import _FakeConnection

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_quality"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server_quality", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _headers(tenant: str) -> dict[str, str]:
    return {
        "x-raku-tenant-id": tenant,
        "x-raku-user-id": "alice",
        "x-raku-groups": json.dumps([]),
        "x-raku-roles": json.dumps(["admin"]),
    }


class TestQualityOperationalEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        srv = _load_server()
        self.system = MvpSystem()
        # The manufacturing overlay wiring expects a _conn attribute; MvpSystem is NOT a
        # ProductionSystem, so the quality/feedback seams still select their in-memory backends.
        self.system._conn = _FakeConnection()
        self.httpd = HTTPServer(("127.0.0.1", 0), srv.make_handler(self.system))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()

    def _json(
        self, path: str, *, tenant: str = T, method: str = "GET", body: dict | None = None
    ) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = _headers(tenant)
        if body is not None:
            headers["content-type"] = "application/json"
        request = Request(f"{self.base}{path}", data=data, headers=headers, method=method)
        with urlopen(request, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_operational_summary_reflects_traffic_feedback_and_principal_tenant(self) -> None:
        self.system.ingest_text(
            tenant_id=T,
            collection_id="manuals",
            document_id="doc_q",
            text="The maintenance interval for pump P-12 is ninety days per the manual.",
        )
        self.system.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        ans = self.system.answer(claims(T, "alice"), "maintenance interval for pump P-12?")
        self.assertEqual(ans.status, "ok")
        self._json(
            "/internal/feedback",
            method="POST",
            body={"answer_id": ans.correlation_id, "subject": "user", "rating": 1},
        )

        summary = self._json("/internal/quality/operational")
        self.assertEqual(summary["query_count"], 1)
        self.assertEqual(summary["status_counts"], {"ok": 1})
        self.assertGreater(summary["p95_ms"], 0.0)
        self.assertEqual(summary["recent_refusals"], [])
        self.assertEqual(summary["low_rating_count"], 1)

        # Another tenant's principal sees NOTHING of tenant_quality — the tenant scope comes
        # from the headers the API facade forwards, never from a query parameter.
        other = self._json("/internal/quality/operational", tenant="tenant_other")
        self.assertEqual(other["query_count"], 0)
        self.assertEqual(other["status_counts"], {})
        self.assertEqual(other["low_rating_count"], 0)


if __name__ == "__main__":
    unittest.main()
