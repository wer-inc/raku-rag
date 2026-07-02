"""T028 — /internal/phone/* route wiring on the deployed answer-service boundary (US1).

Boots the REAL `make_handler` HTTP stack in-process (ephemeral port) over an in-memory system —
`build_manufacturing_system_for_base` is swapped for the in-memory `ManufacturingSystem`
composition because the production builder requires a live Postgres connection. Asserts route
dispatch, header-derived identity, the X-Internal-Auth gate, and the simulate → turn → handoff →
scenario surfaces end-to-end over HTTP.
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
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    ManufacturingDocumentMetadata,
)

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_phone_http"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server_phone_http", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _headers(roles=("tenant_admin",), user="alice", tenant=T, extra=None):
    headers = {
        "content-type": "application/json",
        "x-raku-tenant-id": tenant,
        "x-raku-user-id": user,
        "x-raku-groups": "[]",
        "x-raku-roles": json.dumps(list(roles)),
    }
    headers.update(extra or {})
    return headers


class TestPhoneAnswerServiceRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = _load_server()
        system = MvpSystem()
        system.grant(T, ScopeType.COLLECTION, "faq", SubjectType.USER, "alice")
        mfg = ManufacturingSystem(base_system=system)
        mfg.ingest_manufacturing(
            tenant_id=T,
            collection_id="faq",
            document_id="FAQ-HOURS",
            text="当社の営業時間は平日9時から18時までです。土日祝日は休業です。",
            metadata=ManufacturingDocumentMetadata(
                tenant_id=T,
                document_id="FAQ-HOURS",
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-06-01",
            ),
        )
        # The production builder needs Postgres (`base._conn`); reuse the already-composed
        # in-memory manufacturing system for the handler instead.
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

    def test_simulate_and_turn_routes(self) -> None:
        status, payload = self._request(
            "POST",
            "/internal/phone/calls/simulate",
            {
                "caller": {"phone_number": "+81300001234"},
                "collection_id": "faq",
                "utterances": [{"type": "speech", "text": "営業時間を教えてください"}],
            },
        )
        self.assertEqual(status, 202, payload)
        self.assertEqual(payload["tenant_id"], T)
        self.assertTrue(payload["call_id"].startswith("call_"))
        self.assertEqual(payload["turns"][0]["ai_action"], "answer_with_citations")
        self.assertEqual(payload["turns"][0]["citations"][0]["document_id"], "FAQ-HOURS")

        call_id = payload["call_id"]
        status, turn = self._request(
            "POST",
            f"/internal/phone/calls/{call_id}/turns",
            {"event_type": "speech", "text": "人につないでください"},
        )
        self.assertEqual(status, 200, turn)
        self.assertEqual(turn["ai_action"], "handoff")
        handoff_id = turn["handoff"]["handoff_package_id"]

        status, detail = self._request("GET", f"/internal/phone/calls/{call_id}")
        self.assertEqual(status, 200)
        self.assertTrue(detail["transcript"])

        status, listing = self._request("GET", "/internal/phone/calls")
        self.assertEqual(status, 200)
        self.assertTrue(any(item["call_id"] == call_id for item in listing["items"]))

        status, package = self._request(
            "GET", f"/internal/phone/handoffs/{handoff_id}", headers=_headers(roles=("operator",))
        )
        self.assertEqual(status, 200)
        self.assertEqual(package["reason"], "customer_requested_human")

        status, accepted = self._request(
            "POST",
            f"/internal/phone/handoffs/{handoff_id}/accept",
            {"operator_id": "op_1"},
            headers=_headers(roles=("operator",)),
        )
        self.assertEqual(status, 200)
        self.assertEqual(accepted["status"], "accepted")

    def test_identity_comes_from_headers_not_body(self) -> None:
        status, payload = self._request(
            "POST",
            "/internal/phone/calls/simulate",
            {
                "tenant_id": "tenant_evil",
                "utterances": [{"type": "speech", "text": "営業時間を教えてください"}],
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(payload["tenant_id"], T)

    def test_scenario_lifecycle_routes(self) -> None:
        status, created = self._request(
            "POST",
            "/internal/phone/scenarios",
            {"name": "FAQ基本対応", "intent": "faq", "scenario_id": "faq-http"},
        )
        self.assertEqual(status, 201, created)
        self.assertEqual(created["scenario_id"], "faq-http")

        status, updated = self._request(
            "PUT",
            "/internal/phone/scenarios/faq-http/versions/scv_1",
            {"fallback_message": "確認して担当者におつなぎします。"},
        )
        self.assertEqual(status, 200, updated)

        for action in ("submit-review", "approve", "publish"):
            status, acted = self._request(
                "POST", f"/internal/phone/scenarios/faq-http/versions/scv_1/{action}", {}
            )
            self.assertEqual(status, 200, (action, acted))
        self.assertEqual(acted["active_version_id"], "scv_1")

        status, listing = self._request("GET", "/internal/phone/scenarios")
        self.assertEqual(status, 200)
        self.assertTrue(any(s["scenario_id"] == "faq-http" for s in listing["items"]))

        status, preview = self._request(
            "POST",
            "/internal/phone/scenarios/faq-http/versions/scv_1/test",
            {"utterances": ["人につないでください"]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(preview["would_handoff"])

        status, rolled = self._request(
            "POST", "/internal/phone/scenarios/faq-http/rollback", {"target_version_id": "scv_1"}
        )
        self.assertEqual(status, 200, rolled)
        self.assertEqual(rolled["rollback_target_version_id"], "scv_1")

    def test_internal_auth_gate_guards_phone_routes(self) -> None:
        original = self.srv._INTERNAL_AUTH_SECRET
        self.srv._INTERNAL_AUTH_SECRET = "phone-secret"  # pragma: allowlist secret
        try:
            status, payload = self._request("GET", "/internal/phone/calls")
            self.assertEqual(status, 401)
            self.assertEqual(payload["error"], "internal_auth_required")
            status, _ = self._request(
                "GET",
                "/internal/phone/calls",
                headers=_headers(extra={"X-Internal-Auth": "phone-secret"}),
            )
            self.assertEqual(status, 200)
        finally:
            self.srv._INTERNAL_AUTH_SECRET = original


if __name__ == "__main__":
    unittest.main()
