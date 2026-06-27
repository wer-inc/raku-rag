"""Build ingestable documents from configured data sources.

The sync layer intentionally emits plain ``SyncDocument`` values. The existing ingest
pipeline remains the only place that parses, chunks, embeds, indexes, and records runs.
"""

from __future__ import annotations

import base64
import hashlib
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Mapping
from urllib.parse import unquote, urlencode, urljoin, urlparse

from raku_rag.providers.connectors import S3Connector

# The fetch seam returns ``(raw_bytes, content_type)``. The default implementation (``_fetch_url``)
# accepts ``headers``/``data``/``method``/``allow_hosts`` keyword arguments; the web crawl path calls
# it positionally with just the URL. Tests inject their own callable.
FetchUrl = Callable[..., tuple[bytes, str]]

# SSRF defence: connectors fetch user-supplied URLs, so every outbound hop must resolve to a public
# address and (for SaaS connectors) match an explicit host allowlist. See ssrf-connector-preship-gate.
_PARSEABLE_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/html",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
# File extensions the ingest parser actually understands. ``_content_type_for_ref`` falls back to
# text/plain for anything unknown, so file connectors must gate on the extension to avoid feeding a
# binary (e.g. .pdf, .png) into the text parser.
_PARSEABLE_EXTENSIONS = (".txt", ".md", ".markdown", ".csv", ".html", ".htm", ".docx", ".xlsx")


_CGNAT_V4 = ipaddress.ip_network("100.64.0.0/10")  # RFC 6598 carrier-grade NAT


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any non-public address an SSRF attacker could pivot through."""

    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.version == 4 and ip in _CGNAT_V4)
    )


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connect to a pre-validated IP (closing the resolve→connect DNS-rebinding window) while still
    sending the original Host header."""

    def __init__(self, host: str, port: int, *, pinned_ip: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:  # pragma: no cover - exercised via live sockets only
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self, host: str, port: int, *, pinned_ip: str, context: ssl.SSLContext, timeout: float
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:  # pragma: no cover - exercised via live sockets only
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        # server_hostname stays the real host so SNI + certificate validation are unaffected.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _make_connection(scheme: str, host: str, port: int, pinned_ip: str, timeout: float):
    if scheme == "https":
        return _PinnedHTTPSConnection(
            host, port, pinned_ip=pinned_ip, context=ssl.create_default_context(), timeout=timeout
        )
    return _PinnedHTTPConnection(host, port, pinned_ip=pinned_ip, timeout=timeout)


# SaaS connector host allowlists (suffix match): user input cannot redirect fetches off-vendor.
_KINTONE_HOSTS = ("cybozu.com", "kintone.com")
_CONFLUENCE_HOSTS = ("atlassian.net",)
_NOTION_HOSTS = ("api.notion.com",)
_BOX_HOSTS = ("box.com", "boxcloud.com")
# Drive download/export 302-redirect off googleapis.com to googleusercontent.com / docs.google.com,
# and _fetch_url re-validates the allowlist on EVERY hop — all three hosts must be present or the
# byte fetch is rejected. (_fetch_url drops Authorization across hosts; Drive's redirect is pre-signed.)
_GDRIVE_HOSTS = ("googleapis.com", "googleusercontent.com", "docs.google.com")
_NOTION_VERSION = "2022-06-28"
# Google-native docs cannot be downloaded with alt=media; they must be exported. Map native mimeType
# -> export mimeType (each is in _PARSEABLE_CONTENT_TYPES). text/html preserves Docs structure better
# than text/plain. Other native types (folder/drawing/form) are skipped.
_GDRIVE_EXPORT = {
    "application/vnd.google-apps.document": "text/html",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


def _host_allowed(host: str, allow_hosts: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    for suffix in allow_hosts:
        suffix = suffix.lower().lstrip(".")
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def _assert_public_host(url: str, *, allow_hosts: tuple[str, ...] | None = None):
    """Reject non-http(s) schemes, disallowed hosts, and hosts resolving to non-public addresses.

    Returns the validated ``getaddrinfo`` record (family + sockaddr) so the caller can pin the
    connection to the exact IP that was checked, closing the resolve→connect DNS-rebinding window.
    Every resolved address must be public; a single private/loopback/etc. result fails the URL.
    """

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme or 'none'}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL host is required")
    if allow_hosts is not None and not _host_allowed(host, allow_hosts):
        raise ValueError(f"host not allowed by connector allowlist: {host}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:  # pragma: no cover - environment dependent
        raise ValueError(f"could not resolve host: {host}") from exc
    pinned = None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_blocked_ip(ip):
            raise ValueError(f"host resolves to a non-public address: {host} -> {ip}")
        if pinned is None:
            pinned = info
    if pinned is None:
        raise ValueError(f"could not resolve host: {host}")
    return pinned


def _assert_public_db_host(host: str, *, allow_private: bool) -> None:
    """SSRF guard for relational connectors. A DB host often lives on a private network, so internal
    addresses require an explicit ``allow_private_host`` opt-in instead of being allowed silently.

    Residual (accepted): unlike the HTTP path this does not IP-pin — the DB driver re-resolves the
    host on connect, so a DNS-rebind between this check and connect is theoretically possible. The
    threat is bounded (operator-supplied DSN + credentials, not anonymous SSRF), so it is documented
    rather than pinned (psycopg/pymysql do not expose a pre-resolved-IP connect seam)."""

    if allow_private:
        return
    if not host:
        raise ValueError(
            "could not determine DB host for SSRF validation; set allow_private_host to override"
        )
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:  # pragma: no cover - environment dependent
        raise ValueError(f"could not resolve DB host: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_blocked_ip(ip):
            raise ValueError(
                f"DB host resolves to a non-public address: {host} -> {ip}; "
                "set allow_private_host to override"
            )


@dataclass(frozen=True)
class SyncDocument:
    document_id: str
    document_ref: str
    raw: bytes
    content_type: str


def build_sync_documents(
    source_id: str,
    datasource: Mapping[str, object],
    *,
    body: Mapping[str, object] | None = None,
    limit: int = 25,
    fetch_url: FetchUrl | None = None,
) -> list[SyncDocument]:
    """Resolve a saved datasource into one or more documents for ingest."""

    body = body or {}
    config = _mapping(datasource.get("config"))
    source_type = str(config.get("source_type") or datasource.get("type") or "").lower()
    effective_limit = _int_value(body, config, ("limit", "max_documents"), default=limit)
    effective_limit = max(1, min(effective_limit, 100))

    if source_type == "s3":
        return _s3_documents(source_id, config, body, effective_limit)
    if source_type == "url":
        return _url_documents(
            source_id,
            config,
            body,
            effective_limit,
            fetch_url=fetch_url or _fetch_url,
        )
    if source_type in {"db", "mysql", "postgres", "postgresql", "database"}:
        return _db_documents(source_id, config, body, effective_limit)
    if source_type == "kintone":
        return [
            _kintone_document(source_id, config, body, effective_limit, fetch_url or _fetch_url)
        ]
    if source_type == "confluence":
        return _confluence_documents(
            source_id, config, body, effective_limit, fetch_url or _fetch_url
        )
    if source_type == "notion":
        return _notion_documents(source_id, config, body, effective_limit, fetch_url or _fetch_url)
    if source_type == "box":
        return _box_documents(source_id, config, body, effective_limit, fetch_url or _fetch_url)
    if source_type == "google_drive":
        return _gdrive_documents(source_id, config, body, effective_limit, fetch_url or _fetch_url)
    raise ValueError(f"unsupported datasource source_type: {source_type or 'unknown'}")


def _s3_documents(
    source_id: str,
    config: Mapping[str, object],
    body: Mapping[str, object],
    limit: int,
) -> list[SyncDocument]:
    bucket = _str_value(body, config, ("bucket", "bucket_name"))
    if not bucket:
        raise ValueError("S3 datasource requires bucket")
    endpoint_url = _str_value(body, config, ("endpoint_url", "s3_endpoint_url"))
    access_key_id = _str_value(body, config, ("access_key_id", "access_key"))
    secret_access_key = _str_value(body, config, ("secret_access_key", "secret_key"))
    # SSRF/credential-exfil guard: a custom endpoint must carry its own credentials so a
    # user-supplied endpoint can never be reached with ambient instance-role creds, and it must
    # resolve to a public address unless an operator explicitly opts in to a private endpoint.
    if endpoint_url:
        if not (access_key_id and secret_access_key):
            raise ValueError(
                "custom S3 endpoint_url requires explicit access_key_id and secret_access_key"
            )
        if not _bool_value(body, config, ("allow_private_host", "allow_private")):
            _assert_public_host(endpoint_url)
    connector = S3Connector(
        bucket=bucket,
        endpoint_url=endpoint_url,
        region_name=_str_value(body, config, ("region", "region_name")),
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )
    ref = _str_value(body, config, ("document_ref", "ref", "s3_uri"))
    object_key = _str_value(body, config, ("object_key", "key"))
    if ref:
        refs = [ref]
    elif object_key:
        refs = [f"s3://{bucket}/{object_key.lstrip('/')}"]
    else:
        refs = connector.list_refs(prefix=_str_value(body, config, ("prefix",)), limit=limit)
    if not refs:
        raise ValueError("S3 datasource did not match any objects")
    return [
        SyncDocument(
            document_id=_document_id(source_id, ref),
            document_ref=ref,
            raw=connector.fetch(ref),
            content_type=_content_type_for_ref(ref),
        )
        for ref in refs[:limit]
    ]


def _url_documents(
    source_id: str,
    config: Mapping[str, object],
    body: Mapping[str, object],
    limit: int,
    *,
    fetch_url: FetchUrl,
) -> list[SyncDocument]:
    start_url = _str_value(body, config, ("target_url", "url"))
    if not start_url:
        raise ValueError("URL datasource requires target_url")
    depth = max(0, min(_int_value(body, config, ("crawl_depth", "depth"), default=0), 2))
    queue: list[tuple[str, int]] = [(start_url, 0)]
    seen: set[str] = set()
    docs: list[SyncDocument] = []
    start_host = urlparse(start_url).netloc
    while queue and len(docs) < limit:
        url, current_depth = queue.pop(0)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or url in seen:
            continue
        if parsed.netloc != start_host:
            continue
        seen.add(url)
        raw, content_type = fetch_url(url)
        docs.append(
            SyncDocument(
                document_id=_document_id(source_id, url),
                document_ref=url,
                raw=raw,
                content_type=(
                    content_type if content_type in _PARSEABLE_CONTENT_TYPES else "text/plain"
                ),
            )
        )
        if current_depth < depth and "html" in content_type:
            for link in _extract_links(raw, url):
                if link not in seen:
                    queue.append((link, current_depth + 1))
    if not docs:
        raise ValueError("URL datasource did not fetch any documents")
    return docs


def _db_documents(
    source_id: str,
    config: Mapping[str, object],
    body: Mapping[str, object],
    limit: int,
) -> list[SyncDocument]:
    """Resolve a relational datasource into one document. Supports PostgreSQL and MySQL/MariaDB.

    The engine is taken from an explicit ``db_engine``/``engine`` config value, otherwise inferred
    from the connection-string scheme (``mysql://`` / ``mariadb://`` → MySQL, else PostgreSQL).
    """

    dsn = _str_value(body, config, ("connection_string", "dsn"))
    table_name = _str_value(body, config, ("table_name", "table"))
    if not dsn or not table_name:
        raise ValueError("DB datasource requires connection_string and table_name")
    # SSRF guard: a user-supplied DSN can point at an internal database. Require an explicit opt-in
    # for non-public hosts rather than connecting to anything the connection string names.
    _assert_public_db_host(
        _db_host(dsn),
        allow_private=_bool_value(body, config, ("allow_private_host", "allow_private")),
    )
    updated_column = _str_value(body, config, ("updated_column",))
    engine = _db_engine(body, config, dsn)
    if engine == "mysql":
        rows = _mysql_rows(dsn, table_name, updated_column, limit)
        ref = f"mysql://{table_name}"
        title = f"MySQL {table_name}"
    else:
        rows = _postgres_rows(dsn, table_name, updated_column, limit)
        ref = f"postgres://{table_name}"
        title = f"PostgreSQL {table_name}"
    text = _rows_to_text(title, rows)
    return [
        SyncDocument(
            document_id=_document_id(source_id, ref),
            document_ref=ref,
            raw=text.encode("utf-8"),
            content_type="text/plain",
        )
    ]


def _db_host(dsn: str) -> str:
    """Best-effort host extraction for SSRF validation: URL DSNs (``mysql://`` / ``postgresql://``)
    via urlparse, libpq key=value DSNs via a ``host=`` token. Empty when it cannot be determined."""

    parsed = urlparse(dsn)
    if parsed.scheme and parsed.hostname:
        return parsed.hostname
    match = re.search(r"(?:^|\s)host=([^\s]+)", dsn)
    return match.group(1) if match else ""


def _db_engine(body: Mapping[str, object], config: Mapping[str, object], dsn: str) -> str:
    explicit = _str_value(body, config, ("db_engine", "engine", "driver")).lower()
    if explicit in {"mysql", "mariadb"}:
        return "mysql"
    if explicit in {"postgres", "postgresql", "pg"}:
        return "postgres"
    scheme = urlparse(dsn).scheme.lower()
    if scheme.startswith(("mysql", "mariadb")):
        return "mysql"
    return "postgres"


def _postgres_rows(
    dsn: str, table_name: str, updated_column: str, limit: int
) -> list[Mapping[str, object]]:
    table_sql = _quote_table(table_name, '"')
    order_sql = (
        f" ORDER BY {_quote_ident(updated_column, chr(34))} DESC NULLS LAST"
        if updated_column
        else ""
    )
    query = f"SELECT * FROM {table_sql}{order_sql} LIMIT %s"
    return _postgres_fetch(dsn, query, (limit,))


def _postgres_fetch(
    dsn: str, query: str, params: tuple
) -> list[Mapping[str, object]]:  # pragma: no cover - patched in tests / needs a live driver
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore
    except Exception as exc:
        raise RuntimeError("psycopg is required for PostgreSQL datasource sync") from exc

    with psycopg.connect(dsn) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


def _mysql_connect(dsn: str):  # pragma: no cover - patched in tests / needs a live driver
    try:
        import pymysql  # type: ignore
        from pymysql.cursors import DictCursor  # type: ignore
    except Exception as exc:
        raise RuntimeError("pymysql is required for MySQL datasource sync") from exc

    parsed = urlparse(dsn)
    return pymysql.connect(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=(parsed.path or "/").lstrip("/") or None,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )


def _mysql_rows(
    dsn: str, table_name: str, updated_column: str, limit: int
) -> list[Mapping[str, object]]:
    table_sql = _quote_table(table_name, "`")
    # MySQL has no NULLS LAST; "(col IS NULL), col DESC" emulates it so a nullable change-detection
    # column does not surface oldest/empty rows first under LIMIT.
    if updated_column:
        col = _quote_ident(updated_column, "`")
        order_sql = f" ORDER BY ({col} IS NULL), {col} DESC"
    else:
        order_sql = ""
    query = f"SELECT * FROM {table_sql}{order_sql} LIMIT %s"
    conn = _mysql_connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(query, (limit,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _kintone_document(
    source_id: str,
    config: Mapping[str, object],
    body: Mapping[str, object],
    limit: int,
    fetch_url: FetchUrl,
) -> SyncDocument:
    subdomain = _str_value(body, config, ("subdomain", "domain", "base_url"))
    api_token = _str_value(body, config, ("api_token", "token"))
    app_id = _str_value(body, config, ("app_id", "app"))
    if not subdomain or not api_token or not app_id:
        raise ValueError("kintone datasource requires subdomain, api_token, and app_id")
    base_url = (
        subdomain if subdomain.startswith(("http://", "https://")) else f"https://{subdomain}"
    )
    query = urlencode({"app": app_id, "query": f"limit {limit}"})
    url = f"{base_url.rstrip('/')}/k/v1/records.json?{query}"
    raw, _content_type = fetch_url(
        url,
        headers={"X-Cybozu-API-Token": api_token},
        allow_hosts=_KINTONE_HOSTS,
    )
    payload = json.loads(raw.decode("utf-8"))
    records = payload.get("records") or []
    rows: list[dict[str, object]] = []
    for record in records[:limit]:
        if isinstance(record, dict):
            rows.append(
                {
                    key: _kintone_value(value)
                    for key, value in record.items()
                    if not key.startswith("$")
                }
            )
    text = _rows_to_text(f"kintone app {app_id}", rows)
    ref = f"{base_url.rstrip('/')}/k/v1/records.json?app={app_id}"
    return SyncDocument(
        document_id=_document_id(source_id, ref),
        document_ref=ref,
        raw=text.encode("utf-8"),
        content_type="text/plain",
    )


def _confluence_documents(
    source_id: str,
    config: Mapping[str, object],
    body: Mapping[str, object],
    limit: int,
    fetch_url: FetchUrl,
) -> list[SyncDocument]:
    """Confluence Cloud pages via the REST API token method (email + API token, Basic auth)."""

    site_url = _str_value(body, config, ("site_url", "base_url", "url"))
    space_key = _str_value(body, config, ("space_key", "space"))
    email = _str_value(body, config, ("email", "username", "user"))
    api_token = _str_value(body, config, ("api_token", "token"))
    if not site_url or not space_key or not email or not api_token:
        raise ValueError("Confluence datasource requires site_url, space_key, email, and api_token")
    base = site_url.rstrip("/")
    auth = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    query = urlencode(
        {
            "spaceKey": space_key,
            "limit": limit,
            "status": "current",
            "expand": "body.storage,version",
        }
    )
    raw, _ct = fetch_url(
        f"{base}/rest/api/content?{query}", headers=headers, allow_hosts=_CONFLUENCE_HOSTS
    )
    payload = json.loads(raw.decode("utf-8"))
    docs: list[SyncDocument] = []
    for page in _api_results(payload, "results", "Confluence")[:limit]:
        if not isinstance(page, dict):
            continue
        page_id = str(page.get("id") or "")
        title = str(page.get("title") or page_id or "page")
        storage = page.get("body") or {}
        storage = storage.get("storage") if isinstance(storage, dict) else {}
        storage_html = (storage or {}).get("value") if isinstance(storage, dict) else ""
        webui = (
            ((page.get("_links") or {}).get("webui"))
            if isinstance(page.get("_links"), dict)
            else ""
        )
        webui = webui or f"/pages/{page_id}"
        ref = f"{base}{webui}" if webui.startswith("/") else webui
        # Emit text/html so the existing HtmlTextParser strips Confluence storage markup at ingest.
        document = f"<h1>{html.escape(title)}</h1>\n{storage_html or ''}"
        docs.append(
            SyncDocument(
                document_id=_document_id(source_id, ref),
                document_ref=ref,
                raw=document.encode("utf-8"),
                content_type="text/html",
            )
        )
    if not docs:
        raise ValueError("Confluence datasource returned no pages")
    return docs


def _notion_documents(
    source_id: str,
    config: Mapping[str, object],
    body: Mapping[str, object],
    limit: int,
    fetch_url: FetchUrl,
) -> list[SyncDocument]:
    """Notion pages via the integration-token method. A database is queried for its pages, then each
    page's block children are expanded to Markdown. A single page_id is also supported."""

    token = _str_value(body, config, ("integration_token", "api_token", "token"))
    database_id = _str_value(body, config, ("database_id", "target_database", "database"))
    page_id = _str_value(body, config, ("page_id", "page"))
    if not token or (not database_id and not page_id):
        raise ValueError("Notion datasource requires integration_token and database_id or page_id")
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Accept": "application/json",
    }
    pages: list[tuple[str, str]] = []
    if database_id:
        data = json.dumps({"page_size": min(limit, 100)}).encode("utf-8")
        raw, _ct = fetch_url(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers={**headers, "Content-Type": "application/json"},
            data=data,
            method="POST",
            allow_hosts=_NOTION_HOSTS,
        )
        payload = json.loads(raw.decode("utf-8"))
        for result in _api_results(payload, "results", "Notion")[:limit]:
            if isinstance(result, dict) and result.get("id"):
                pages.append((str(result["id"]), _notion_page_title(result)))
    else:
        pages.append((page_id, ""))

    docs: list[SyncDocument] = []
    for pid, title in pages[:limit]:
        raw, _ct = fetch_url(
            f"https://api.notion.com/v1/blocks/{pid}/children?page_size=100",
            headers=headers,
            allow_hosts=_NOTION_HOSTS,
        )
        payload = json.loads(raw.decode("utf-8"))
        markdown = _notion_blocks_to_markdown(_api_results(payload, "results", "Notion"))
        ref = f"https://www.notion.so/{pid.replace('-', '')}"
        heading = f"# {title}\n\n" if title else ""
        body_text = f"{heading}{markdown}".strip() or title or pid
        docs.append(
            SyncDocument(
                document_id=_document_id(source_id, ref),
                document_ref=ref,
                raw=body_text.encode("utf-8"),
                content_type="text/markdown",
            )
        )
    if not docs:
        raise ValueError("Notion datasource returned no pages")
    return docs


def _box_documents(
    source_id: str,
    config: Mapping[str, object],
    body: Mapping[str, object],
    limit: int,
    fetch_url: FetchUrl,
) -> list[SyncDocument]:
    """Box files in a folder via the developer/access-token method (Bearer). Files are downloaded and
    ingested by content type inferred from their name; unparseable types are skipped."""

    token = _str_value(body, config, ("access_token", "developer_token", "token", "api_token"))
    folder_id = _str_value(body, config, ("folder_id", "folder")) or "0"
    if not token:
        raise ValueError(
            "Box datasource requires access_token (folder_id defaults to the root folder)"
        )
    list_headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    query = urlencode({"limit": min(max(limit, 1) * 4, 1000), "fields": "id,name,type"})
    raw, _ct = fetch_url(
        f"https://api.box.com/2.0/folders/{folder_id}/items?{query}",
        headers=list_headers,
        allow_hosts=_BOX_HOSTS,
    )
    payload = json.loads(raw.decode("utf-8"))
    docs: list[SyncDocument] = []
    for entry in _api_results(payload, "entries", "Box"):
        if not isinstance(entry, dict) or entry.get("type") != "file":
            continue
        name = str(entry.get("name") or "")
        file_id = str(entry.get("id") or "")
        if not name or not file_id:
            continue
        if not name.lower().endswith(_PARSEABLE_EXTENSIONS):
            continue  # skip binaries the text/office parser cannot read (.pdf, images, …)
        content_type = _content_type_for_name(name)
        file_raw, _dl_ct = fetch_url(
            f"https://api.box.com/2.0/files/{file_id}/content",
            headers={"Authorization": f"Bearer {token}"},
            allow_hosts=_BOX_HOSTS,
        )
        ref = f"box://{folder_id}/{name}"
        docs.append(
            SyncDocument(
                document_id=_document_id(source_id, ref),
                document_ref=ref,
                raw=file_raw,
                content_type=content_type,
            )
        )
        if len(docs) >= limit:
            break
    if not docs:
        raise ValueError("Box datasource returned no parseable files")
    return docs


def _gdrive_folder_id(raw: str) -> str:
    """Accept a bare folder id or a Drive folder URL; return the id (defaults to 'root')."""
    raw = (raw or "").strip()
    if not raw:
        return "root"
    if "drive.google.com" in raw and "/folders/" in raw:
        tail = raw.split("/folders/", 1)[1]
        return tail.split("?", 1)[0].split("/", 1)[0] or "root"
    return raw


def _gdrive_documents(
    source_id: str,
    config: Mapping[str, object],
    body: Mapping[str, object],
    limit: int,
    fetch_url: FetchUrl,
) -> list[SyncDocument]:
    """Google Drive files in a folder via OAuth (Bearer). The access token is the FRESH token the
    answer-service injected into ``body`` from the stored refresh token — never read from config.
    Native Google docs are exported (Docs->HTML, Sheets->CSV, Slides->text); uploaded binaries are
    downloaded via alt=media and gated on parseable extensions; content type is computed locally."""

    token = str(body.get("fresh_access_token") or body.get("access_token") or "").strip()
    if not token:
        raise ValueError(
            "Google Drive datasource requires an active OAuth connection (reconnect required)"
        )
    folder_id = _gdrive_folder_id(
        _str_value(body, config, ("folder_id", "folder", "target_folder"))
    )
    auth_header = {"Authorization": f"Bearer {token}"}
    list_headers = {**auth_header, "Accept": "application/json"}
    page_size = min(max(limit, 1) * 2, 1000)

    docs: list[SyncDocument] = []
    page_token = ""
    for _page in range(50):  # hard cap on pages so a runaway listing cannot loop forever
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType)",
            "pageSize": page_size,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        raw, _ct = fetch_url(
            f"https://www.googleapis.com/drive/v3/files?{urlencode(params)}",
            headers=list_headers,
            allow_hosts=_GDRIVE_HOSTS,
        )
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            message = payload["error"].get("message") or payload["error"]
            raise ValueError(f"Google Drive API error: {message}")
        for entry in _api_results(payload, "files", "Google Drive"):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "")
            file_id = str(entry.get("id") or "")
            mime = str(entry.get("mimeType") or "")
            if not name or not file_id:
                continue
            if mime in _GDRIVE_EXPORT:
                export_mime = _GDRIVE_EXPORT[mime]
                file_raw, _dl = fetch_url(
                    f"https://www.googleapis.com/drive/v3/files/{file_id}/export?"
                    + urlencode({"mimeType": export_mime}),
                    headers=auth_header,
                    allow_hosts=_GDRIVE_HOSTS,
                )
                content_type = export_mime
            elif mime.startswith("application/vnd.google-apps"):
                continue  # folders, drawings, forms — not ingestable
            else:
                if not name.lower().endswith(_PARSEABLE_EXTENSIONS):
                    continue  # skip binaries the text/office parser cannot read (.pdf, images, …)
                file_raw, _dl = fetch_url(
                    f"https://www.googleapis.com/drive/v3/files/{file_id}?"
                    + urlencode({"alt": "media", "supportsAllDrives": "true"}),
                    headers=auth_header,
                    allow_hosts=_GDRIVE_HOSTS,
                )
                content_type = _content_type_for_name(name)
            ref = f"gdrive://{folder_id}/{name}"
            docs.append(
                SyncDocument(
                    document_id=_document_id(source_id, ref),
                    document_ref=ref,
                    raw=file_raw,
                    content_type=content_type,
                )
            )
            if len(docs) >= limit:
                break
        page_token = payload.get("nextPageToken") if isinstance(payload, dict) else ""
        if not page_token or len(docs) >= limit:
            break
    if not docs:
        raise ValueError("Google Drive datasource returned no parseable files")
    return docs


def _notion_page_title(page: Mapping[str, object]) -> str:
    properties = page.get("properties")
    if not isinstance(properties, dict):
        return ""
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _notion_rich_text(prop.get("title"))
    return ""


def _notion_rich_text(rich_text: object) -> str:
    if not isinstance(rich_text, list):
        return ""
    parts: list[str] = []
    for span in rich_text:
        if isinstance(span, dict):
            text = span.get("plain_text")
            if text is None:
                inner = span.get("text")
                text = inner.get("content") if isinstance(inner, dict) else None
            if text:
                parts.append(str(text))
    return "".join(parts)


def _notion_blocks_to_markdown(blocks: object) -> str:
    if not isinstance(blocks, list):
        return ""
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        payload = block.get(block_type)
        text = _notion_rich_text(payload.get("rich_text")) if isinstance(payload, dict) else ""
        if block_type == "heading_1":
            lines.append(f"# {text}")
        elif block_type == "heading_2":
            lines.append(f"## {text}")
        elif block_type == "heading_3":
            lines.append(f"### {text}")
        elif block_type == "bulleted_list_item":
            lines.append(f"- {text}")
        elif block_type == "numbered_list_item":
            lines.append(f"1. {text}")
        elif block_type == "to_do":
            checked = bool(payload.get("checked")) if isinstance(payload, dict) else False
            lines.append(f"- [{'x' if checked else ' '}] {text}")
        elif block_type in {"quote", "callout"}:
            lines.append(f"> {text}")
        elif block_type == "code":
            language = payload.get("language") if isinstance(payload, dict) else ""
            lines.append(f"```{language or ''}\n{text}\n```")
        elif text:
            lines.append(text)
    return "\n".join(line for line in lines).strip()


def _open_validated(
    url: str,
    *,
    headers: Mapping[str, str],
    data: bytes | None,
    method: str,
    allow_hosts: tuple[str, ...] | None,
    timeout: float,
):
    """Validate ``url`` for SSRF, pin the connection to the validated IP, and perform one request.

    Returns ``(status, response_headers, body)``. Redirects are NOT followed here — the caller
    re-validates each hop. This is the single network egress point for the connectors."""

    pinned = _assert_public_host(url, allow_hosts=allow_hosts)
    parsed = urlparse(url)
    pinned_ip = pinned[4][0]
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    conn = _make_connection(parsed.scheme, parsed.hostname, port, pinned_ip, timeout)
    try:
        conn.request(method, path, body=data, headers=dict(headers))
        response = conn.getresponse()
        body = response.read()
        return response.status, response.headers, body
    finally:
        conn.close()


def _fetch_url(
    url: str,
    headers: Mapping[str, str] | None = None,
    *,
    data: bytes | None = None,
    method: str | None = None,
    allow_hosts: tuple[str, ...] | None = None,
    max_redirects: int = 4,
) -> tuple[bytes, str]:
    """SSRF-guarded fetch. Pins each hop to a validated public IP, never auto-follows redirects
    (each ``Location`` is re-validated), and optionally enforces a per-connector host allowlist.
    Supports GET/POST with a body."""

    current = url
    request_data = data
    request_method = method or ("POST" if data is not None else "GET")
    request_headers = {"User-Agent": "raku-rag-source-sync/0.1", **dict(headers or {})}
    current_host = (urlparse(url).hostname or "").lower()
    for _hop in range(max_redirects + 1):
        status, response_headers, raw = _open_validated(
            current,
            headers=request_headers,
            data=request_data,
            method=request_method,
            allow_hosts=allow_hosts,
            timeout=15,
        )
        if status in {301, 302, 303, 307, 308}:
            location = response_headers.get("Location")
            if not location:
                break
            current = urljoin(current, location)
            next_host = (urlparse(current).hostname or "").lower()
            if next_host != current_host:
                # Drop credentials when the redirect crosses hosts so a Bearer/Basic token is never
                # replayed to a different host (e.g. Box's 302 to a pre-signed boxcloud.com URL).
                request_headers = {
                    k: v for k, v in request_headers.items() if k.lower() != "authorization"
                }
            current_host = next_host
            if status in {301, 302, 303}:
                request_method = "GET"
                request_data = None
            continue
        if status >= 400:
            raise ValueError(f"fetch failed with HTTP {status} for {url}")
        content_type = response_headers.get_content_type() or "text/plain"
        if content_type not in {"text/html", "text/plain", "text/markdown", "text/csv"}:
            content_type = "text/plain"
        return raw, content_type
    raise ValueError(f"too many redirects fetching {url}")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


def _extract_links(raw: bytes, base_url: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return [urljoin(base_url, href).split("#", 1)[0] for href in parser.links]


def _rows_to_text(title: str, rows: list[Mapping[str, object]]) -> str:
    lines = [f"# {title}", ""]
    for index, row in enumerate(rows, start=1):
        lines.append(f"## row {index}")
        for key, value in row.items():
            lines.append(f"{key}: {_json_value(value)}")
        lines.append("")
    if len(lines) == 2:
        lines.append("(no rows)")
    return "\n".join(lines).strip()


def _kintone_value(value: object) -> object:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _json_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _api_results(payload: object, key: str, label: str) -> list:
    """Pull a list out of a SaaS API JSON body, raising a clear error when the API returned an error
    object (e.g. ``{"message": ...}``) instead of the expected ``{key: [...]}`` collection."""

    if isinstance(payload, dict):
        results = payload.get(key)
        if isinstance(results, list):
            return results
        message = payload.get("message") or payload.get("error")
        if message:
            raise ValueError(f"{label} API error: {message}")
    return []


def _str_value(
    body: Mapping[str, object],
    config: Mapping[str, object],
    keys: tuple[str, ...],
    *,
    default: str = "",
) -> str:
    for source in (body, config):
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return default


def _int_value(
    body: Mapping[str, object],
    config: Mapping[str, object],
    keys: tuple[str, ...],
    *,
    default: int,
) -> int:
    raw = _str_value(body, config, keys, default=str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_value(
    body: Mapping[str, object],
    config: Mapping[str, object],
    keys: tuple[str, ...],
) -> bool:
    return _str_value(body, config, keys).strip().lower() in {"1", "true", "yes", "on"}


def _document_id(source_id: str, ref: str) -> str:
    digest = hashlib.sha1(ref.encode("utf-8")).hexdigest()[:10]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", ref.rsplit("/", 1)[-1] or source_id)
    stem = stem.strip("-._")[:48] or "document"
    return f"{source_id}-{stem}-{digest}"


def _content_type_for_ref(ref: str) -> str:
    return _content_type_for_path(urlparse(ref).path.lower())


def _content_type_for_name(name: str) -> str:
    # Use the raw file name (not urlparse) so names containing '?' or '#' are not truncated before
    # their extension and mis-typed as text/plain.
    return _content_type_for_path(name.lower())


def _content_type_for_path(path: str) -> str:
    if path.endswith((".html", ".htm")):
        return "text/html"
    if path.endswith((".md", ".markdown")):
        return "text/markdown"
    if path.endswith(".csv"):
        return "text/csv"
    if path.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if path.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return "text/plain"


def _quote_table(name: str, quote: str = '"') -> str:
    parts = [part.strip() for part in name.split(".") if part.strip()]
    if not parts or len(parts) > 2:
        raise ValueError("table_name must be table or schema.table")
    return ".".join(_quote_ident(part, quote) for part in parts)


def _quote_ident(name: str, quote: str = '"') -> str:
    # Identifiers are whitelisted to a safe character class, so no value-level escaping is needed;
    # ``quote`` selects PostgreSQL double-quotes vs MySQL backticks.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise ValueError(f"unsafe SQL identifier: {name}")
    return f"{quote}{name}{quote}"
