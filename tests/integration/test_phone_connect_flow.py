"""L014 — Connect adapter end-to-end over the REAL in-process answer-service HTTP stack.

lambda_handler (Connect event fixtures) → internal ALB surface (make_handler) → 022 phone layer.
Proves the live-call path (call_start → grounded turn → handoff → hangup) without any AWS/billed
dependency, including the phone_gateway service-role authorization.
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

from raku_rag.app import MvpSystem
from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    ManufacturingDocumentMetadata,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / "tests/fixtures/phone/connect_events.json").read_text("utf-8"))
T = "demo"

DID_MAP = {
    "+815055550100": {
        "tenant_id": T,
        "user_id": "phone-gateway",
        "groups": [],
        "collection_id": "faq",
    }
}


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ConnectAdapterFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        srv = _load_module(ROOT / "apps/answer-service/server.py", "answer_service_connect_flow")
        system = MvpSystem()
        # Knowledge is granted to the PHONE SERVICE USER — the existing ACL model decides what
        # the phone channel can answer (research.md Decision 4).
        system.grant(T, ScopeType.COLLECTION, "faq", SubjectType.USER, "phone-gateway")
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
        cls._orig_builder = srv.build_manufacturing_system_for_base
        srv.build_manufacturing_system_for_base = lambda base: mfg
        cls.httpd = HTTPServer(("127.0.0.1", 0), srv.make_handler(system))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.srv = srv

        os.environ["RAKU_INTERNAL_API_BASE"] = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        os.environ["RAKU_PHONE_DID_MAP"] = json.dumps(DID_MAP)
        os.environ["RAKU_PHONE_HANDOFF_URL_BASE"] = "https://stg.example.com/phone"
        cls.adapter = _load_module(
            ROOT / "infra/connect/lambda/connect_phone_adapter.py", "connect_phone_adapter_flow"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.srv.build_manufacturing_system_for_base = cls._orig_builder
        for key in ("RAKU_INTERNAL_API_BASE", "RAKU_PHONE_DID_MAP", "RAKU_PHONE_HANDOFF_URL_BASE"):
            os.environ.pop(key, None)

    def _event(self, name: str, call_id: str | None = None) -> dict:
        event = json.loads(json.dumps(FIXTURES[name]))
        if call_id is not None:
            event["Details"]["ContactData"]["Attributes"]["raku_call_id"] = call_id
        return event

    def test_full_inbound_call_flow(self) -> None:
        # 1) call_start creates the call with the Connect contact identity.
        start = self.adapter.lambda_handler(self._event("call_start"))
        self.assertEqual(start["ok"], "true", start)
        self.assertEqual(start["action"], "continue")
        call_id = start["call_id"]
        self.assertTrue(call_id.startswith("call_"))

        # 2) grounded FAQ turn speaks a short voice answer.
        turn = self.adapter.lambda_handler(self._event("turn_faq", call_id))
        self.assertEqual(turn["action"], "continue", turn)
        self.assertEqual(turn["ai_action"], "answer_with_citations")
        self.assertIn("9時", turn["speech_text"])
        self.assertNotIn("\n", turn["speech_text"])  # voice-rendered, not the screen text

        # 3) 人につないで → handoff branch with operator screen-pop URL.
        handoff = self.adapter.lambda_handler(self._event("turn_handoff", call_id))
        self.assertEqual(handoff["action"], "handoff", handoff)
        self.assertEqual(handoff["handoff_reason"], "customer_requested_human")
        self.assertTrue(handoff["handoff_url"].startswith("https://stg.example.com/phone?handoff="))

        # 4) hangup terminates without error even from handoff_pending.
        end = self.adapter.lambda_handler(self._event("hangup", call_id))
        self.assertIn(end["action"], {"end_call", "continue"})

        # 5) the persisted call is Connect-attributed and holds only the MASKED caller number.
        detail_status, detail = self._read_call_as_admin(call_id)
        self.assertEqual(detail_status, 200)
        blob = json.dumps(detail, ensure_ascii=False)
        self.assertNotIn("+819012345678", blob)
        self.assertIn("+81******5678", blob)

    def _read_call_as_admin(self, call_id: str):
        import urllib.request

        request = urllib.request.Request(
            f"{os.environ['RAKU_INTERNAL_API_BASE']}/internal/phone/calls/{call_id}",
            headers={
                "x-raku-tenant-id": T,
                "x-raku-user-id": "supervisor",
                "x-raku-groups": "[]",
                "x-raku-roles": json.dumps(["tenant_admin"]),
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())


if __name__ == "__main__":
    unittest.main()
