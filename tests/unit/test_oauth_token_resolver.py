from __future__ import annotations

import json
import unittest
import urllib.parse
from types import SimpleNamespace

from raku_rag.persistence.secret_store import InMemorySecretStore
from raku_rag.services.oauth_token_resolver import (
    OAuthConfigError,
    OAuthExchangeError,
    RefreshTokenExpiredError,
    exchange_code,
    resolve_fresh_access_token,
)

_ENV = {
    "GOOGLE_OAUTH_CLIENT_ID": "client-123.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "secret-abc",
}


class RecordingFetch:
    """Fake _fetch_url: records each call, returns canned JSON bytes or raises like the real seam."""

    def __init__(self, *, body: dict | None = None, http_error: int | None = None) -> None:
        self.body = body
        self.http_error = http_error
        self.calls: list[dict] = []

    def __call__(self, url, headers=None, *, data=None, method=None, allow_hosts=None, **kwargs):
        parsed = dict(urllib.parse.parse_qsl((data or b"").decode("utf-8")))
        self.calls.append(
            {"url": url, "headers": dict(headers or {}), "method": method,
             "allow_hosts": allow_hosts, "params": parsed}
        )
        if self.http_error is not None:
            raise ValueError(f"fetch failed with HTTP {self.http_error} for {url}")
        return json.dumps(self.body or {}).encode("utf-8"), "text/plain"


def _conn(secret_ref="gdrive/conn1", tenant="tenant_a"):
    return SimpleNamespace(
        tenant_id=tenant, connection_id="conn1", refresh_token_secret_ref=secret_ref
    )


class ExchangeCodeTest(unittest.TestCase):
    def test_stores_refresh_token_and_returns_access_token(self) -> None:
        store = InMemorySecretStore()
        fetch = RecordingFetch(
            body={"access_token": "at-1", "refresh_token": "rt-1", "scope": "drive.readonly",
                  "expires_in": 3599}
        )
        result = exchange_code(
            "auth-code", "https://app/cb",
            secret_store=store, tenant_id="tenant_a", secret_ref="gdrive/conn1",
            env=_ENV, fetch_url=fetch,
        )
        self.assertEqual(result["access_token"], "at-1")
        self.assertTrue(result["refresh_token_stored"])
        # refresh token is persisted, never returned
        self.assertNotIn("refresh_token", result)
        self.assertEqual(store.retrieve_secret("tenant_a", "gdrive/conn1"), "rt-1")
        # correct grant + endpoint + allowlist
        call = fetch.calls[0]
        self.assertEqual(call["url"], "https://oauth2.googleapis.com/token")
        self.assertEqual(call["params"]["grant_type"], "authorization_code")
        self.assertEqual(call["params"]["code"], "auth-code")
        self.assertEqual(call["params"]["redirect_uri"], "https://app/cb")
        self.assertEqual(call["allow_hosts"], ("googleapis.com",))

    def test_missing_refresh_token_raises(self) -> None:
        store = InMemorySecretStore()
        fetch = RecordingFetch(body={"access_token": "at-1"})  # no refresh_token
        with self.assertRaises(OAuthExchangeError):
            exchange_code("c", "https://app/cb", secret_store=store, tenant_id="t",
                          secret_ref="r", env=_ENV, fetch_url=fetch)

    def test_http_error_raises_exchange_error(self) -> None:
        store = InMemorySecretStore()
        fetch = RecordingFetch(http_error=400)
        with self.assertRaises(OAuthExchangeError):
            exchange_code("bad", "https://app/cb", secret_store=store, tenant_id="t",
                          secret_ref="r", env=_ENV, fetch_url=fetch)

    def test_missing_client_credentials_raises(self) -> None:
        store = InMemorySecretStore()
        fetch = RecordingFetch(body={"refresh_token": "rt"})
        with self.assertRaises(OAuthConfigError):
            exchange_code("c", "https://app/cb", secret_store=store, tenant_id="t",
                          secret_ref="r", env={}, fetch_url=fetch)


class ResolveFreshAccessTokenTest(unittest.TestCase):
    def test_refresh_returns_fresh_access_token(self) -> None:
        store = InMemorySecretStore()
        store.store_secret("tenant_a", "gdrive/conn1", "rt-1")
        fetch = RecordingFetch(body={"access_token": "fresh-at", "expires_in": 3599})
        token = resolve_fresh_access_token(_conn(), store, env=_ENV, fetch_url=fetch)
        self.assertEqual(token, "fresh-at")
        call = fetch.calls[0]
        self.assertEqual(call["params"]["grant_type"], "refresh_token")
        self.assertEqual(call["params"]["refresh_token"], "rt-1")
        self.assertEqual(call["allow_hosts"], ("googleapis.com",))

    def test_missing_secret_is_reconnect_required(self) -> None:
        store = InMemorySecretStore()  # nothing stored
        fetch = RecordingFetch(body={"access_token": "x"})
        with self.assertRaises(RefreshTokenExpiredError):
            resolve_fresh_access_token(_conn(), store, env=_ENV, fetch_url=fetch)
        self.assertEqual(fetch.calls, [])  # never hit Google without a refresh token

    def test_invalid_grant_is_reconnect_required(self) -> None:
        store = InMemorySecretStore()
        store.store_secret("tenant_a", "gdrive/conn1", "revoked-rt")
        fetch = RecordingFetch(http_error=400)  # Google invalid_grant
        with self.assertRaises(RefreshTokenExpiredError):
            resolve_fresh_access_token(_conn(), store, env=_ENV, fetch_url=fetch)

    def test_no_access_token_in_response_raises(self) -> None:
        store = InMemorySecretStore()
        store.store_secret("tenant_a", "gdrive/conn1", "rt")
        fetch = RecordingFetch(body={"expires_in": 3599})  # no access_token
        with self.assertRaises(RefreshTokenExpiredError):
            resolve_fresh_access_token(_conn(), store, env=_ENV, fetch_url=fetch)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
