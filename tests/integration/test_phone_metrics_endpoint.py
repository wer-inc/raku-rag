"""T079 — GET /internal/phone/metrics over the real answer-service HTTP stack (022 US5).

Boots `make_handler` in-process like test_phone_answer_service.py: asserts the metrics route
dispatch, query-string date range, role gating, and that QA knowledge-gap topics from the
quality endpoint surface in the aggregate.
"""

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
from raku_rag.manufacturing.app import ManufacturingSystem

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_phone_metrics"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server_phone_metrics", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _headers(roles=("tenant_admin",), user="alice"):
    return {
        "content-type": "application/json",
        "x-raku-tenant-id": T,
        "x-raku-user-id": user,
        "x-raku-groups": "[]",
        "x-raku-roles": json.dumps(list(roles)),
    }


class TestPhoneMetricsEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = _load_server()
        system = MvpSystem()
        mfg = ManufacturingSystem(base_system=system)
        cls._orig_builder = cls.srv.build_manufacturing_system_for_base
        cls.srv.build_manufacturing_system_for_base = lambda base: mfg
        handler = cls.srv.make_handler(system)
        cls.httpd = HTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.srv.build_manufacturing_system_for_base = cls._orig_builder

    def _request(self, method: str, path: str, body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers=headers or _headers(),
            method=method,
        )
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def test_metrics_aggregate_calls_and_qa_topics_over_http(self) -> None:
        # One handoff call (no evidence in the empty KB) + one hangup call.
        status, first = self._request(
            "POST",
            "/internal/phone/calls/simulate",
            {"utterances": [{"type": "speech", "text": "未知の質問です"}]},
        )
        self.assertEqual(status, 202, first)
        self._request(
            "POST",
            "/internal/phone/calls/simulate",
            {"utterances": [{"type": "hangup"}]},
        )
        status, _ = self._request(
            "POST",
            f"/internal/phone/calls/{first['call_id']}/quality-evaluations",
            {"knowledge_gap_topics": ["返金条件"]},
            headers=_headers(roles=("qa_reviewer",), user="misaki"),
        )
        self.assertEqual(status, 201)

        status, metrics = self._request(
            "GET", "/internal/phone/metrics?from=2000-01-01&to=2100-01-01"
        )
        self.assertEqual(status, 200, metrics)
        self.assertEqual(metrics["summary"]["call_count"], 2)
        self.assertGreaterEqual(metrics["summary"]["handoff_rate"], 0.5)
        topics = {t["key"] for t in metrics["knowledge_gap_topics"]}
        self.assertIn("返金条件", topics)

        status, empty = self._request("GET", "/internal/phone/metrics?from=2100-01-01")
        self.assertEqual(status, 200)
        self.assertEqual(empty["summary"]["call_count"], 0)

    def test_metrics_role_gate_over_http(self) -> None:
        status, payload = self._request(
            "GET", "/internal/phone/metrics", headers=_headers(roles=("qa_reviewer",))
        )
        self.assertEqual(status, 403, payload)


if __name__ == "__main__":
    unittest.main()
