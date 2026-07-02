"""0045 — /internal/uploads registration + upload_id-resolved ingest over the real HTTP stack.

Boots `make_handler` in-process (phone-tests pattern) with a fake S3 connector so the s3://
verification path (bucket allowlist, tenant prefix, HeadObject metadata) runs for real, and
asserts: registration, duplicate refusal, upload_id ingest happy path, one-time consumption,
cross-tenant refusal, ref/record mismatch refusal, and the strict-provenance env gate.
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from raku_rag.app import MvpSystem
from raku_rag.manufacturing.app import ManufacturingSystem

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_upload_prov"
BUCKET = "prov-test-bucket"


def _load_server():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server_upload_prov", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class FakeS3Connector:
    """fetch/object_info for tenants/<T>/uploads/... refs — no real AWS."""

    def fetch(self, ref: str) -> bytes:
        return "検査手順書のテスト本文です。".encode("utf-8")

    def object_info(self, ref: str) -> dict:
        upload_id = ref.rsplit("/", 1)[-1].split(".")[0]
        return {
            "content_length": 128,
            "metadata": {
                "raku-tenant-id": quote(T, safe="")[:180],
                "raku-user-id": "alice",
                "raku-upload-id": upload_id,
            },
        }


def _headers(tenant=T, user="alice"):
    return {
        "content-type": "application/json",
        "x-raku-tenant-id": tenant,
        "x-raku-user-id": user,
        "x-raku-groups": "[]",
        "x-raku-roles": json.dumps(["tenant_admin"]),
    }


class TestIngestUploadProvenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["RAKU_UPLOAD_BUCKET"] = BUCKET
        cls.srv = _load_server()
        system = MvpSystem()

        # MvpSystem has no ingest_document (that's the ProductionSystem pipeline projection);
        # this test targets the PROVENANCE seam around it, so stub a deterministic queued run.
        class _StubRun:
            def __init__(self, document_id: str) -> None:
                self.ingestion_run_id = f"ing_{document_id}"
                self.document_id = document_id
                self.status = "succeeded"
                self.failure_reason = None
                self.chunk_count = 1
                self.sqs_message_id = ""

        system.ingest_document = lambda **kwargs: _StubRun(str(kwargs["document_id"]))
        mfg = ManufacturingSystem(base_system=system)
        cls._orig_builder = cls.srv.build_manufacturing_system_for_base
        cls._orig_connector = cls.srv.default_connector_from_env
        cls.srv.build_manufacturing_system_for_base = lambda base: mfg
        cls.srv.default_connector_from_env = lambda: FakeS3Connector()
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
        cls.srv.default_connector_from_env = cls._orig_connector
        os.environ.pop("RAKU_UPLOAD_BUCKET", None)
        os.environ.pop("RAKU_REQUIRE_UPLOAD_RECORD", None)

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

    def _register(self, upload_id: str, tenant=T):
        key = f"tenants/{quote(tenant, safe='')[:180]}/uploads/2026-07-02/{upload_id}.txt"
        return self._request(
            "POST",
            "/internal/uploads",
            {
                "upload_id": upload_id,
                "bucket": BUCKET,
                "object_key": key,
                "content_type": "text/plain",
                "content_length": 128,
                "filename": "手順書.txt",
            },
            headers=_headers(tenant=tenant),
        )

    def _ingest(self, body_extra: dict, tenant=T, document_id="doc-prov-1"):
        body = {
            "tenant_id": tenant,
            "user_id": "alice",
            "collection_id": "manuals",
            "source_id": "file-manuals",
            "document_id": document_id,
            "content_type": "text/plain",
            **body_extra,
        }
        return self._request("POST", "/internal/ingest", body)

    def test_register_then_ingest_by_upload_id_consumes_once(self) -> None:
        status, record = self._register("up_happy")
        self.assertEqual(status, 201, record)
        self.assertTrue(record["expires_at"])

        self.assertEqual(self._register("up_happy")[0], 409)

        status, ingest = self._ingest({"upload_id": "up_happy"})
        self.assertEqual(status, 202, ingest)
        self.assertTrue(ingest["ingestion_run_id"])

        status, again = self._ingest({"upload_id": "up_happy"}, document_id="doc-prov-2")
        self.assertEqual(status, 200)
        self.assertEqual(again["status"], "failed")
        self.assertIn("already consumed", again["failure_reason"])

    def test_unknown_and_cross_tenant_upload_ids_fail(self) -> None:
        status, payload = self._ingest({"upload_id": "up_missing"})
        self.assertEqual(status, 200)
        self.assertIn("unknown upload_id", payload["failure_reason"])

        self.assertEqual(self._register("up_owned")[0], 201)
        status, payload = self._ingest(
            {"upload_id": "up_owned"}, tenant="tenant_intruder", document_id="doc-x"
        )
        self.assertEqual(status, 200)
        self.assertIn("unknown upload_id", payload["failure_reason"])

    def test_ref_must_match_the_registered_record(self) -> None:
        self.assertEqual(self._register("up_pinned")[0], 201)
        status, payload = self._ingest(
            {
                "upload_id": "up_pinned",
                "document_ref": f"s3://{BUCKET}/tenants/{T}/uploads/2026-07-02/other.txt",
            }
        )
        self.assertEqual(status, 200)
        self.assertIn("does not match", payload["failure_reason"])

    def test_strict_mode_refuses_raw_s3_refs_without_record(self) -> None:
        os.environ["RAKU_REQUIRE_UPLOAD_RECORD"] = "1"
        try:
            status, payload = self._ingest(
                {"document_ref": f"s3://{BUCKET}/tenants/{T}/uploads/2026-07-02/raw.txt"}
            )
            self.assertEqual(status, 200)
            self.assertIn("requires a registered upload_id", payload["failure_reason"])
        finally:
            os.environ.pop("RAKU_REQUIRE_UPLOAD_RECORD", None)


if __name__ == "__main__":
    unittest.main()
