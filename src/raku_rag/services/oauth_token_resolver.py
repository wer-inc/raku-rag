"""Google OAuth token exchange + refresh for the Drive connector (021-gdrive-oauth).

Two operations, both performed in the answer-service (the only process that holds the client
secret and the SecretStore):

* :func:`exchange_code` — at OAuth callback, swap an authorization ``code`` for tokens, persist the
  ``refresh_token`` directly into the :class:`SecretStore`, and return only the short-lived
  ``access_token`` (+ metadata). The refresh token never travels back up the call stack.
* :func:`resolve_fresh_access_token` — at sync time, read the stored refresh token and mint a fresh
  ~1h access token.

HTTP goes through the existing SSRF-guarded ``_fetch_url`` seam (stdlib ``http.client`` under the
hood — no new dependency). That seam raises ``ValueError`` on any HTTP >= 400 and discards the
body, so a rejected refresh/exchange surfaces as :class:`RefreshTokenExpiredError` /
:class:`OAuthExchangeError` ("reconnect required") rather than a silent empty sync.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from typing import Callable, Mapping

from raku_rag.services.datasource_sync import _fetch_url

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
# Token endpoint stays on googleapis.com; no cross-host redirect is expected here.
_GOOGLE_TOKEN_HOSTS = ("googleapis.com",)

FetchUrl = Callable[..., "tuple[bytes, str]"]


class OAuthConfigError(RuntimeError):
    """OAuth client credentials (GOOGLE_OAUTH_CLIENT_ID/SECRET) are not configured."""


class OAuthExchangeError(RuntimeError):
    """The Google token endpoint rejected an authorization-code exchange."""


class RefreshTokenExpiredError(RuntimeError):
    """A refresh token is missing, invalid, or revoked — the connection must be re-authorized."""


class _TokenHttpError(RuntimeError):
    """Internal: the token endpoint returned HTTP >= 400 (body unavailable through the seam)."""


def _client_credentials(env: Mapping[str, str]) -> tuple[str, str]:
    client_id = str(env.get("GOOGLE_OAUTH_CLIENT_ID", ""))
    client_secret = str(env.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    if not client_id or not client_secret:
        raise OAuthConfigError("GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET are not configured")
    return client_id, client_secret


def _post_token(params: dict, *, fetch_url: FetchUrl) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    try:
        raw, _ = fetch_url(
            _GOOGLE_TOKEN_URL,
            headers,
            data=data,
            method="POST",
            allow_hosts=_GOOGLE_TOKEN_HOSTS,
        )
    except ValueError as exc:  # _fetch_url raises on HTTP >= 400 (e.g. 400 invalid_grant)
        raise _TokenHttpError(str(exc)) from exc
    try:
        payload = json.loads(raw or b"{}")
    except (json.JSONDecodeError, ValueError) as exc:
        raise OAuthExchangeError("Google token endpoint returned a non-JSON body") from exc
    return payload if isinstance(payload, dict) else {}


def exchange_code(
    code: str,
    redirect_uri: str,
    *,
    secret_store,
    tenant_id: str,
    secret_ref: str,
    env: Mapping[str, str] | None = None,
    fetch_url: FetchUrl = _fetch_url,
) -> dict:
    """Exchange an authorization ``code`` for tokens; persist the refresh token to ``secret_store``.

    Returns ``{"access_token", "refresh_token_stored": True, "scope", "expires_in"}``. The refresh
    token itself is written to the SecretStore and never returned. Raises :class:`OAuthExchangeError`
    on rejection or when Google returns no refresh token (offline access not granted).
    """
    if not code:
        raise OAuthExchangeError("authorization code is required")
    env = os.environ if env is None else env
    client_id, client_secret = _client_credentials(env)
    try:
        payload = _post_token(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            fetch_url=fetch_url,
        )
    except _TokenHttpError as exc:
        raise OAuthExchangeError(f"authorization code exchange failed: {exc}") from exc

    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise OAuthExchangeError(
            "Google did not return a refresh_token; ensure access_type=offline and prompt=consent"
        )
    secret_store.store_secret(tenant_id, secret_ref, str(refresh_token))
    return {
        "access_token": payload.get("access_token", ""),
        "refresh_token_stored": True,
        "scope": payload.get("scope", ""),
        "expires_in": payload.get("expires_in"),
    }


def resolve_fresh_access_token(
    connection,
    secret_store,
    *,
    env: Mapping[str, str] | None = None,
    fetch_url: FetchUrl = _fetch_url,
) -> str:
    """Mint a fresh access token from the connection's stored refresh token.

    ``connection`` is duck-typed: it needs ``tenant_id`` and ``refresh_token_secret_ref``.
    Raises :class:`RefreshTokenExpiredError` when the secret is missing or Google rejects the
    refresh (reconnect required).
    """
    env = os.environ if env is None else env
    client_id, client_secret = _client_credentials(env)
    try:
        refresh_token = secret_store.retrieve_secret(
            connection.tenant_id, connection.refresh_token_secret_ref
        )
    except KeyError as exc:  # SecretNotFoundError subclasses KeyError
        raise RefreshTokenExpiredError(
            f"no stored refresh token for connection {getattr(connection, 'connection_id', '?')}; "
            "reconnect required"
        ) from exc

    try:
        payload = _post_token(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            fetch_url=fetch_url,
        )
    except _TokenHttpError as exc:
        raise RefreshTokenExpiredError(
            f"refresh token rejected for connection "
            f"{getattr(connection, 'connection_id', '?')}: {exc}; reconnect required"
        ) from exc

    access_token = payload.get("access_token")
    if not access_token:
        raise RefreshTokenExpiredError(
            "Google returned no access_token on refresh; reconnect required"
        )
    return str(access_token)
