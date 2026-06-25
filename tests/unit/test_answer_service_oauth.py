"""021-gdrive: the answer-service OAuth callback + sync-time fresh-token injection glue.

Exercises the two module-level helpers in apps/answer-service/server.py directly (no HTTP / no
Postgres) with in-memory stores and a fake _fetch_url, so the wiring between the callback, the
SecretStore, the connection store, and the sync body is verified offline (stdlib, Tier A).
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from raku_rag.persistence.oauth_connection import InMemoryOAuthConnectionStore, build_connection
from raku_rag.persistence.secret_store import InMemorySecretStore
from raku_rag.services import oauth_token_resolver

ROOT = Path(__file__).resolve().parents[2]
_SERVER = ROOT / "apps/answer-service/server.py"

_ENV = {
    "GOOGLE_OAUTH_CLIENT_ID": "cid.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "csecret",
}


def _load_server():
    spec = importlib.util.spec_from_file_location("answer_service_server", _SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Fetch:
    def __init__(self, body=None, http_error=None):
        self.body, self.http_error, self.calls = body, http_error, []

    def __call__(self, url, headers=None, *, data=None, method=None, allow_hosts=None, **_kw):
        self.calls.append({"url": url, "data": data})
        if self.http_error is not None:
            raise ValueError(f"fetch failed with HTTP {self.http_error} for {url}")
        return json.dumps(self.body or {}).encode("utf-8"), "text/plain"


class AnswerServiceOAuthGlueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = _load_server()

    def setUp(self) -> None:
        self.secrets = InMemorySecretStore()
        self.conns = InMemoryOAuthConnectionStore()

    def test_callback_persists_refresh_token_and_records_connection(self) -> None:
        fetch = _Fetch(body={"access_token": "at", "refresh_token": "rt-9", "scope": "drive.readonly"})
        result = self.server._oauth_google_callback(
            "tenant_a",
            {"code": "auth-code", "redirect_uri": "https://app/cb"},
            secret_store=self.secrets,
            oauth_connections=self.conns,
            env=_ENV,
            fetch_url=fetch,
        )
        cid = result["connection_id"]
        self.assertTrue(result["refresh_token_stored"])
        conn = self.conns.get("tenant_a", cid)
        self.assertIsNotNone(conn)
        # refresh token landed in the SecretStore under the connection's ref, not in the result
        self.assertEqual(self.secrets.retrieve_secret("tenant_a", conn.refresh_token_secret_ref), "rt-9")
        self.assertNotIn("refresh_token", result)

    def test_callback_missing_code_raises_valueerror(self) -> None:
        with self.assertRaises(ValueError):
            self.server._oauth_google_callback(
                "tenant_a", {"redirect_uri": "x"},
                secret_store=self.secrets, oauth_connections=self.conns, env=_ENV, fetch_url=_Fetch(),
            )

    def test_sync_injects_fresh_access_token_for_google_drive(self) -> None:
        # seed a stored connection + refresh token
        conn = build_connection(tenant_id="tenant_a", source_id="src-1", provider="google_drive")
        self.conns.upsert(conn)
        self.secrets.store_secret("tenant_a", conn.refresh_token_secret_ref, "rt")
        body: dict = {}
        fetch = _Fetch(body={"access_token": "FRESH-AT"})
        datasource = {
            "type": "google_drive",
            "config": {"source_type": "google_drive", "connection_id": conn.connection_id},
        }
        self.server._inject_gdrive_access_token(
            "tenant_a", "src-1", datasource, body,
            secret_store=self.secrets, oauth_connections=self.conns, env=_ENV, fetch_url=fetch,
        )
        self.assertEqual(body["fresh_access_token"], "FRESH-AT")

    def test_sync_is_noop_for_non_gdrive(self) -> None:
        body: dict = {}
        self.server._inject_gdrive_access_token(
            "tenant_a", "src-1", {"type": "box", "config": {"source_type": "box"}}, body,
            secret_store=self.secrets, oauth_connections=self.conns, env=_ENV, fetch_url=_Fetch(),
        )
        self.assertNotIn("fresh_access_token", body)

    def test_sync_without_connection_is_reconnect_required(self) -> None:
        with self.assertRaises(ValueError):
            self.server._inject_gdrive_access_token(
                "tenant_a", "src-1",
                {"type": "google_drive", "config": {"source_type": "google_drive", "connection_id": "missing"}},
                {}, secret_store=self.secrets, oauth_connections=self.conns, env=_ENV, fetch_url=_Fetch(),
            )

    def test_sync_invalid_grant_is_reconnect_required(self) -> None:
        conn = build_connection(tenant_id="tenant_a", source_id="src-1", provider="google_drive")
        self.conns.upsert(conn)
        self.secrets.store_secret("tenant_a", conn.refresh_token_secret_ref, "revoked")
        with self.assertRaises(oauth_token_resolver.RefreshTokenExpiredError):
            self.server._inject_gdrive_access_token(
                "tenant_a", "src-1",
                {"type": "google_drive", "config": {"source_type": "google_drive", "connection_id": conn.connection_id}},
                {}, secret_store=self.secrets, oauth_connections=self.conns, env=_ENV,
                fetch_url=_Fetch(http_error=400),
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
