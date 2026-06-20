from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol

JsonObject = dict[str, Any]


class Transport(Protocol):
    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]: ...


class RakuRagError(RuntimeError):
    def __init__(self, status_code: int, payload: Any, headers: Mapping[str, str]) -> None:
        self.status_code = status_code
        self.payload = payload
        self.headers = dict(headers)
        message = payload.get("message") if isinstance(payload, dict) else None
        super().__init__(str(message or f"raku-rag API returned HTTP {status_code}"))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_user_token(
    *,
    tenant_id: str,
    user_id: str,
    groups: list[str] | tuple[str, ...] = (),
    roles: list[str] | tuple[str, ...] = (),
    secret: str | None = None,
) -> str:
    """Create the local HMAC `X-User-Token` used by the NestJS facade.

    Production callers should pass a token issued by their own identity boundary. This helper mirrors
    `apps/api/src/auth/principal.ts` for local development and tests.
    """

    payload = {
        "groups": list(groups),
        "roles": list(roles),
        "tenant_id": tenant_id,
        "user_id": user_id,
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_secret = secret or os.environ.get("RAKU_TOKEN_SIGNING_SECRET") or "dev-secret-change-me"
    sig = hmac.new(signing_secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return f"{body}.{_b64url(sig)}"


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
) -> tuple[int, Mapping[str, str], bytes]:
    req = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(
            req, timeout=timeout
        ) as res:  # noqa: S310 - URL is caller supplied API base.
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


class RakuRagClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        user_token: str,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_token = user_token
        self.timeout = timeout
        self._transport = transport or _default_transport

    def health(self) -> JsonObject:
        return self._request("GET", "/health", auth=False)

    def openapi(self) -> JsonObject:
        return self._request("GET", "/openapi.json", auth=False)

    def whoami(self) -> JsonObject:
        return self._request("GET", "/whoami")

    def search(
        self, query: str, *, collection_id: str | None = None, top_k: int | None = None
    ) -> JsonObject:
        payload: JsonObject = {"query": query}
        if collection_id is not None:
            payload["collection_id"] = collection_id
        if top_k is not None:
            payload["top_k"] = top_k
        return self._request("POST", "/search", payload)

    def answer(self, query: str, *, collection_id: str | None = None) -> JsonObject:
        payload: JsonObject = {"query": query}
        if collection_id is not None:
            payload["collection_id"] = collection_id
        return self._request("POST", "/answer", payload)

    def ingest(
        self,
        *,
        collection_id: str,
        source_id: str,
        document_id: str,
        ref: str,
        content_type: str | None = None,
    ) -> JsonObject:
        payload: JsonObject = {
            "collection_id": collection_id,
            "source_id": source_id,
            "document_id": document_id,
            "ref": ref,
        }
        if content_type is not None:
            payload["content_type"] = content_type
        return self._request("POST", "/ingest", payload)

    def jobs(self, *, status: str | None = None, source_id: str | None = None) -> JsonObject:
        return self._request("GET", "/admin/jobs", query={"status": status, "source_id": source_id})

    def source_sync_status(self, source_id: str) -> JsonObject:
        return self._request("GET", f"/admin/sources/{_quote(source_id)}/sync-status")

    def ingestion_run(self, ingestion_run_id: str) -> JsonObject:
        return self._request("GET", f"/admin/ingestion-runs/{_quote(ingestion_run_id)}")

    def retry_ingestion_run(self, ingestion_run_id: str) -> JsonObject:
        return self._request("POST", f"/admin/ingestion-runs/{_quote(ingestion_run_id)}/retry")

    def document_processing_status(self, document_id: str) -> JsonObject:
        return self._request("GET", f"/admin/documents/{_quote(document_id)}/processing-status")

    def delete_document(self, document_id: str) -> JsonObject:
        return self._request("DELETE", f"/admin/documents/{_quote(document_id)}")

    def reindex_collection(
        self, collection_id: str, request: Mapping[str, Any] | None = None
    ) -> JsonObject:
        return self._request(
            "POST", f"/admin/collections/{_quote(collection_id)}/reindex", dict(request or {})
        )

    def datasources(self, *, collection_id: str | None = None) -> list[JsonObject]:
        return self._request("GET", "/admin/datasources", query={"collection_id": collection_id})

    def datasource(self, source_id: str) -> JsonObject:
        return self._request("GET", f"/admin/datasources/{_quote(source_id)}")

    def put_datasource(self, source_id: str, settings: Mapping[str, Any]) -> JsonObject:
        return self._request("PUT", f"/admin/datasources/{_quote(source_id)}", dict(settings))

    def query_profiles(self, *, collection_id: str | None = None) -> list[JsonObject]:
        return self._request("GET", "/admin/query-profiles", query={"collection_id": collection_id})

    def query_profile(self, profile_id: str) -> JsonObject:
        return self._request("GET", f"/admin/query-profiles/{_quote(profile_id)}")

    def put_query_profile(self, profile_id: str, settings: Mapping[str, Any]) -> JsonObject:
        return self._request("PUT", f"/admin/query-profiles/{_quote(profile_id)}", dict(settings))

    def provider_policies(self, *, collection_id: str | None = None) -> list[JsonObject]:
        return self._request(
            "GET", "/admin/provider-policies", query={"collection_id": collection_id}
        )

    def provider_policy(self, provider_policy_id: str) -> JsonObject:
        return self._request("GET", f"/admin/provider-policies/{_quote(provider_policy_id)}")

    def put_provider_policy(
        self, provider_policy_id: str, settings: Mapping[str, Any]
    ) -> JsonObject:
        return self._request(
            "PUT", f"/admin/provider-policies/{_quote(provider_policy_id)}", dict(settings)
        )

    def validate_provider_policy(
        self, provider_policy_id: str, request: Mapping[str, Any]
    ) -> JsonObject:
        return self._request(
            "POST", f"/admin/provider-policies/{_quote(provider_policy_id)}/validate", dict(request)
        )

    def retrieval_profiles(self, *, collection_id: str | None = None) -> list[JsonObject]:
        return self._request(
            "GET", "/admin/retrieval-profiles", query={"collection_id": collection_id}
        )

    def retrieval_profile(self, retrieval_profile_id: str) -> JsonObject:
        return self._request("GET", f"/admin/retrieval-profiles/{_quote(retrieval_profile_id)}")

    def put_retrieval_profile(
        self, retrieval_profile_id: str, settings: Mapping[str, Any]
    ) -> JsonObject:
        return self._request(
            "PUT", f"/admin/retrieval-profiles/{_quote(retrieval_profile_id)}", dict(settings)
        )

    def benchmark_retrieval_profile(
        self, retrieval_profile_id: str, request: Mapping[str, Any]
    ) -> JsonObject:
        return self._request(
            "POST",
            f"/admin/retrieval-profiles/{_quote(retrieval_profile_id)}/benchmark",
            dict(request),
        )

    def logging_policies(self, *, collection_id: str | None = None) -> list[JsonObject]:
        return self._request(
            "GET", "/admin/logging-policies", query={"collection_id": collection_id}
        )

    def logging_policy(self, logging_policy_id: str) -> JsonObject:
        return self._request("GET", f"/admin/logging-policies/{_quote(logging_policy_id)}")

    def put_logging_policy(self, logging_policy_id: str, settings: Mapping[str, Any]) -> JsonObject:
        return self._request(
            "PUT", f"/admin/logging-policies/{_quote(logging_policy_id)}", dict(settings)
        )

    def acl(self) -> JsonObject:
        return self._request("GET", "/admin/acl")

    def update_acl(self, request: Mapping[str, Any]) -> JsonObject:
        return self._request("PUT", "/admin/acl", dict(request))

    def budgets(
        self, *, scope_type: str | None = None, scope_id: str | None = None
    ) -> list[JsonObject]:
        return self._request(
            "GET", "/admin/budgets", query={"scope_type": scope_type, "scope_id": scope_id}
        )

    def update_budgets(self, request: Mapping[str, Any]) -> JsonObject:
        return self._request("PUT", "/admin/budgets", dict(request))

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        query: Mapping[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        url = self._url(path, query)
        headers = {"accept": "application/json"}
        body: bytes | None = None
        if payload is not None:
            headers["content-type"] = "application/json"
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if auth:
            headers["authorization"] = f"Bearer {self.api_key}"
            headers["x-user-token"] = self.user_token

        status, response_headers, response_body = self._transport(
            method, url, headers, body, self.timeout
        )
        parsed = _parse_json(response_body)
        if status >= 400:
            raise RakuRagError(status, parsed, response_headers)
        return parsed

    def _url(self, path: str, query: Mapping[str, Any] | None = None) -> str:
        url = f"{self.base_url}/{path.lstrip('/')}"
        pairs = [(k, v) for k, v in (query or {}).items() if v is not None and v != ""]
        if pairs:
            url = f"{url}?{urllib.parse.urlencode(pairs)}"
        return url


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _parse_json(body: bytes) -> Any:
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return {"raw": body.decode("utf-8", errors="replace")}
