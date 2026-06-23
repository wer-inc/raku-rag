"""Manufacturing governance endpoints on the answer-service boundary."""

from __future__ import annotations

import importlib.util
import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from raku_rag.app import MvpSystem
from tests.manufacturing.unit.test_durable_manufacturing_wiring import _FakeConnection

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_mfg"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _headers() -> dict[str, str]:
    return {
        "x-raku-tenant-id": T,
        "x-raku-user-id": "admin",
        "x-raku-groups": json.dumps(["ops"]),
        "x-raku-roles": json.dumps(["admin"]),
    }


class TestManufacturingGovernanceEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        srv = _load_server()
        system = MvpSystem()
        system._conn = _FakeConnection()
        self.httpd = HTTPServer(("127.0.0.1", 0), srv.make_handler(system))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()

    def _json(self, path: str, *, method: str = "GET", body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = _headers()
        if body is not None:
            headers["content-type"] = "application/json"
        request = Request(f"{self.base}{path}", data=data, headers=headers, method=method)
        with urlopen(request, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_policy_update_is_durable_and_visible_in_audit_export(self) -> None:
        initial = self._json("/internal/manufacturing/policy/data-use")
        self.assertEqual(initial["policy_version"], "1")
        self.assertTrue(initial["no_train_default"])

        updated = self._json(
            "/internal/manufacturing/policy/data-use",
            method="PUT",
            body={"retention_customer": 730},
        )
        self.assertEqual(updated["retention_customer"], 730)
        self.assertEqual(updated["updated_by"], "admin")

        status = self._json("/internal/manufacturing/governance/status")
        self.assertEqual(status["retention"]["retention_customer_days"], 730)

        exported = self._json("/internal/manufacturing/audit/export?fmt=dict")
        self.assertEqual(exported["format"], "dict")
        self.assertEqual(exported["records"][0]["action"], "policy.retention.change")


if __name__ == "__main__":
    unittest.main()
