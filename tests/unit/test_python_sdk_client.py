from __future__ import annotations

import base64
import json
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk/python"))

from raku_rag_sdk import RakuRagClient, RakuRagError, make_user_token  # noqa: E402


class FakeTransport:
    def __init__(self, responses: list[tuple[int, Mapping[str, str], Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body.decode("utf-8")) if body else None,
                "timeout": timeout,
            }
        )
        status, response_headers, payload = self.responses.pop(0)
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        return status, response_headers, encoded


class PythonSdkClientTest(unittest.TestCase):
    def test_make_user_token_matches_facade_payload_shape(self) -> None:
        token = make_user_token(
            tenant_id="tenant_a",
            user_id="alice",
            groups=["ops"],
            roles=["reader"],
            secret="secret",
        )
        body, sig = token.split(".")
        self.assertGreater(len(sig), 16)
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        self.assertEqual(
            payload,
            {
                "groups": ["ops"],
                "roles": ["reader"],
                "tenant_id": "tenant_a",
                "user_id": "alice",
            },
        )

    def test_public_health_omits_auth_headers(self) -> None:
        transport = FakeTransport([(200, {"api-version": "1"}, {"status": "ok"})])
        client = RakuRagClient(
            base_url="http://api.test/v1/",
            api_key="local-dev-key",
            user_token="user-token",
            transport=transport,
        )

        self.assertEqual(client.health()["status"], "ok")
        call = transport.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["url"], "http://api.test/v1/health")
        self.assertNotIn("authorization", call["headers"])
        self.assertNotIn("x-user-token", call["headers"])

    def test_answer_sends_auth_headers_and_json_body(self) -> None:
        transport = FakeTransport(
            [
                (
                    200,
                    {"api-version": "1"},
                    {"status": "ok", "text": "ninety days", "citations": [], "used_chunks": []},
                )
            ]
        )
        client = RakuRagClient(
            base_url="http://api.test/v1",
            api_key="local-dev-key",
            user_token="user-token",
            timeout=3.5,
            transport=transport,
        )

        res = client.answer("maintenance interval?", collection_id="manuals")
        self.assertEqual(res["status"], "ok")
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "http://api.test/v1/answer")
        self.assertEqual(call["headers"]["authorization"], "Bearer local-dev-key")
        self.assertEqual(call["headers"]["x-user-token"], "user-token")
        self.assertEqual(call["headers"]["content-type"], "application/json")
        self.assertEqual(
            call["body"], {"query": "maintenance interval?", "collection_id": "manuals"}
        )
        self.assertEqual(call["timeout"], 3.5)

    def test_admin_helpers_encode_paths_and_queries(self) -> None:
        transport = FakeTransport(
            [
                (200, {}, [{"provider_policy_id": "default"}]),
                (200, {}, {"allowed": False, "reasons": ["opt-in required"]}),
                (200, {}, {"source_id": "src/a", "provider_config_audit_event_id": "aud_1"}),
                (202, {}, {"reindex_plan_id": "rp_1", "status": "planned"}),
                (200, {}, {"grants": []}),
                (200, {}, {"budgets": [{"budget_id": "tenant:tenant_a", "limit": 100}]}),
            ]
        )
        client = RakuRagClient(
            base_url="http://api.test/v1",
            api_key="local-dev-key",
            user_token="user-token",
            transport=transport,
        )

        self.assertEqual(
            client.provider_policies(collection_id="manuals")[0]["provider_policy_id"], "default"
        )
        self.assertFalse(
            client.validate_provider_policy(
                "default",
                {"operation": "parse", "provider": "azure_document_intelligence"},
            )["allowed"]
        )
        client.put_datasource("src/a", {"collection_id": "manuals", "type": "object_storage"})
        self.assertEqual(
            client.reindex_collection("manuals", {"document_ids": ["d1"], "reason": "manual"})[
                "reindex_plan_id"
            ],
            "rp_1",
        )
        client.update_acl({"grants": []})
        client.update_budgets(
            {"budgets": [{"scope_type": "tenant", "scope_id": "tenant_a", "limit": 100}]}
        )

        self.assertEqual(
            [call["url"] for call in transport.calls],
            [
                "http://api.test/v1/admin/provider-policies?collection_id=manuals",
                "http://api.test/v1/admin/provider-policies/default/validate",
                "http://api.test/v1/admin/datasources/src%2Fa",
                "http://api.test/v1/admin/collections/manuals/reindex",
                "http://api.test/v1/admin/acl",
                "http://api.test/v1/admin/budgets",
            ],
        )
        self.assertEqual(transport.calls[2]["method"], "PUT")

    def test_http_errors_raise_structured_exception(self) -> None:
        transport = FakeTransport(
            [(502, {"api-version": "1"}, {"message": "answer-service unreachable"})]
        )
        client = RakuRagClient(
            base_url="http://api.test/v1",
            api_key="local-dev-key",
            user_token="user-token",
            transport=transport,
        )

        with self.assertRaises(RakuRagError) as ctx:
            client.search("query")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.payload["message"], "answer-service unreachable")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
