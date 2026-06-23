"""HTTP error-contract for the manufacturing draft lifecycle on the answer-service boundary.

Regression for the review finding "out-of-order / invalid draft transitions return 500 (→ 502 at the
NestJS facade) instead of a 4xx". The safety behaviour was always correct (the record is never
mutated); this pins that the *status code* is now a precise client error:
  - out-of-order transition (review before assign) -> 409 Conflict
  - invalid input (unknown DraftType, bad decision) -> 422 Unprocessable
Mirrors tests/integration/test_manufacturing_governance_endpoint.py (boots make_handler over MvpSystem).
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
        "content-type": "application/json",
    }


class TestManufacturingDraftErrorContract(unittest.TestCase):
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

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8")
        request = Request(f"{self.base}{path}", data=data, headers=_headers(), method="POST")
        try:
            with urlopen(request, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:  # 4xx/5xx
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_review_before_assign_is_409_not_500(self) -> None:
        status, draft = self._post("/internal/manufacturing/drafts", {"kind": "checklist"})
        self.assertEqual(status, 200)
        artifact_id = draft["artifact_id"]

        code, body = self._post(
            f"/internal/manufacturing/drafts/{artifact_id}/review", {"decision": "approved"}
        )
        self.assertEqual(code, 409, f"out-of-order review should be 409 Conflict, got {code}: {body}")

    def test_invalid_draft_type_is_422_not_500(self) -> None:
        code, body = self._post("/internal/manufacturing/drafts", {"kind": "sop"})
        self.assertEqual(code, 422, f"unknown DraftType should be 422, got {code}: {body}")

    def test_invalid_review_decision_is_422(self) -> None:
        _, draft = self._post("/internal/manufacturing/drafts", {"kind": "checklist"})
        artifact_id = draft["artifact_id"]
        self._post(
            f"/internal/manufacturing/drafts/{artifact_id}/assign", {"reviewer_id": "carol"}
        )
        code, _ = self._post(
            f"/internal/manufacturing/drafts/{artifact_id}/review", {"decision": "bogus"}
        )
        self.assertEqual(code, 422, "an invalid review decision should be 422")


if __name__ == "__main__":
    unittest.main()
