from __future__ import annotations

import base64
import email.message
import json
import unittest
from unittest.mock import patch

from raku_rag.services import datasource_sync as ds
from raku_rag.services.datasource_sync import (
    _GDRIVE_HOSTS,
    _assert_public_host,
    _host_allowed,
    _quote_ident,
    _quote_table,
    build_sync_documents,
)


def _http_headers(values: dict) -> email.message.Message:
    message = email.message.Message()
    for key, value in values.items():
        message[key] = value
    return message


class FakeResponse:
    def __init__(self, status: int, headers: email.message.Message, body: bytes) -> None:
        self.status = status
        self.headers = headers
        self._body = body

    def read(self) -> bytes:
        return self._body


class FakeHTTPConnection:
    def __init__(self, response: FakeResponse, sink: list) -> None:
        self._response = response
        self.sink = sink

    def request(self, method, path, body=None, headers=None):
        self.sink.append({"method": method, "path": path, "body": body, "headers": headers})

    def getresponse(self) -> FakeResponse:
        return self._response

    def close(self) -> None:
        pass


class FakeS3Connector:
    def __init__(self, **kwargs) -> None:
        self.bucket = kwargs["bucket"]

    def list_refs(self, *, prefix: str = "", limit: int = 25) -> list[str]:
        return [f"s3://{self.bucket}/{prefix}a.txt", f"s3://{self.bucket}/{prefix}b.csv"][:limit]

    def fetch(self, ref: str) -> bytes:
        return f"body for {ref}".encode("utf-8")


class RecordingFetch:
    """A fake of the ``fetch_url`` seam that routes by URL predicate and records every call."""

    def __init__(self, routes) -> None:
        self.routes = routes  # list[(predicate(url)->bool, (bytes, content_type))]
        self.calls: list[dict] = []

    def __call__(
        self,
        url,
        headers=None,
        *,
        data=None,
        method=None,
        allow_hosts=None,
        **_kwargs,
    ):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers or {}),
                "data": data,
                "method": method,
                "allow_hosts": allow_hosts,
            }
        )
        for predicate, response in self.routes:
            if predicate(url):
                return response
        raise AssertionError(f"no route for {url}")


class FakeDBCursor:
    def __init__(self, rows, sink) -> None:
        self.rows = rows
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def execute(self, query, params=None):
        self.sink.append((query, params))

    def fetchall(self):
        return self.rows


class FakeDBConn:
    def __init__(self, rows, sink) -> None:
        self.rows = rows
        self.sink = sink
        self.closed = False

    def cursor(self):
        return FakeDBCursor(self.rows, self.sink)

    def close(self):
        self.closed = True


class TestDatasourceSync(unittest.TestCase):
    def test_s3_datasource_builds_documents_from_prefix(self) -> None:
        datasource = {
            "collection_id": "manuals",
            "config": {
                "source_type": "s3",
                "bucket": "docs",
                "prefix": "manuals/",
            },
        }

        with patch("raku_rag.services.datasource_sync.S3Connector", FakeS3Connector):
            docs = build_sync_documents("s3-src", datasource, limit=10)

        self.assertEqual(
            [doc.document_ref for doc in docs],
            ["s3://docs/manuals/a.txt", "s3://docs/manuals/b.csv"],
        )
        self.assertEqual([doc.content_type for doc in docs], ["text/plain", "text/csv"])
        self.assertTrue(all(doc.raw.startswith(b"body for s3://docs/") for doc in docs))

    def test_url_datasource_fetches_start_url_and_same_host_links(self) -> None:
        responses = {
            "https://example.test/start": (
                b'<html><body><a href="/next">next</a><a href="https://other.test/out">out</a></body></html>',
                "text/html",
            ),
            "https://example.test/next": (b"next page", "text/plain"),
        }

        def fetch(url: str):
            return responses[url]

        docs = build_sync_documents(
            "web-src",
            {
                "config": {
                    "source_type": "url",
                    "target_url": "https://example.test/start",
                    "crawl_depth": "1",
                }
            },
            limit=5,
            fetch_url=fetch,
        )

        self.assertEqual(
            [doc.document_ref for doc in docs],
            ["https://example.test/start", "https://example.test/next"],
        )
        self.assertEqual(docs[0].content_type, "text/html")
        self.assertEqual(docs[1].raw, b"next page")

    def test_url_datasource_preserves_csv_content_type_for_mapping_preview(self) -> None:
        def fetch(url: str):
            self.assertEqual(url, "https://example.test/faq.csv")
            return (b"question,answer\nQ,A\n", "text/csv")

        docs = build_sync_documents(
            "faq-url",
            {"config": {"source_type": "url", "target_url": "https://example.test/faq.csv"}},
            limit=1,
            fetch_url=fetch,
        )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].content_type, "text/csv")

    def test_db_mysql_uses_backtick_quoting_and_explicit_engine(self) -> None:
        sink: list = []
        rows = [{"id": 1, "summary": "alpha"}, {"id": 2, "summary": "beta"}]

        def fake_connect(dsn: str):
            self.assertTrue(dsn.startswith("mysql://"))
            return FakeDBConn(rows, sink)

        with patch("raku_rag.services.datasource_sync._mysql_connect", fake_connect):
            docs = build_sync_documents(
                "db-src",
                {
                    "config": {
                        "source_type": "db",
                        "db_engine": "mysql",
                        "connection_string": "mysql://u:p@8.8.8.8/app",
                        "table_name": "public.cases",
                        "updated_column": "updated_at",
                    }
                },
                limit=5,
            )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].document_ref, "mysql://public.cases")
        self.assertEqual(docs[0].content_type, "text/plain")
        self.assertIn(b"alpha", docs[0].raw)
        query, params = sink[0]
        self.assertIn("`public`.`cases`", query)
        self.assertIn("`updated_at`", query)
        self.assertNotIn('"', query)  # MySQL uses backticks, never double-quotes
        self.assertEqual(params, (5,))

    def test_db_mysql_engine_inferred_from_connection_string_scheme(self) -> None:
        with patch(
            "raku_rag.services.datasource_sync._mysql_connect",
            lambda dsn: FakeDBConn([{"x": 1}], []),
        ):
            docs = build_sync_documents(
                "db2",
                {
                    "config": {
                        "source_type": "db",
                        "connection_string": "mysql://u@8.8.8.8/app",
                        "table_name": "t",
                    }
                },
                limit=3,
            )
        self.assertEqual(docs[0].document_ref, "mysql://t")

    def test_db_postgres_quotes_identifiers_and_nulls_last(self) -> None:
        captured: dict = {}

        def fake_fetch(dsn, query, params):
            captured.update(dsn=dsn, query=query, params=params)
            return [{"id": 1, "summary": "alpha"}]

        with patch("raku_rag.services.datasource_sync._postgres_fetch", fake_fetch):
            docs = build_sync_documents(
                "pg",
                {
                    "config": {
                        "source_type": "db",
                        "connection_string": "postgresql://u@8.8.8.8:5432/app",
                        "table_name": "public.cases",
                        "updated_column": "updated_at",
                    }
                },
                limit=7,
            )
        self.assertEqual(docs[0].document_ref, "postgres://public.cases")
        self.assertIn('"public"."cases"', captured["query"])
        self.assertIn('"updated_at" DESC NULLS LAST', captured["query"])
        self.assertEqual(captured["params"], (7,))

    def test_db_rejects_private_host_without_optin(self) -> None:
        with self.assertRaises(ValueError):
            build_sync_documents(
                "db",
                {
                    "config": {
                        "source_type": "db",
                        "db_engine": "mysql",
                        "connection_string": "mysql://u@10.0.0.5/app",
                        "table_name": "t",
                    }
                },
                limit=3,
            )

    def test_db_private_host_allowed_with_explicit_optin(self) -> None:
        with patch(
            "raku_rag.services.datasource_sync._mysql_connect",
            lambda dsn: FakeDBConn([{"x": 1}], []),
        ):
            docs = build_sync_documents(
                "db",
                {
                    "config": {
                        "source_type": "db",
                        "db_engine": "mysql",
                        "connection_string": "mysql://u@10.0.0.5/app",
                        "table_name": "t",
                        "allow_private_host": "true",
                    }
                },
                limit=3,
            )
        self.assertEqual(docs[0].document_ref, "mysql://t")

    def test_quote_helpers_reject_sql_identifier_injection(self) -> None:
        for bad in ("cases; DROP TABLE x", 'a"b', "a`b", "1col", "", "a b", "a.b"):
            with self.subTest(ident=bad):
                with self.assertRaises(ValueError):
                    _quote_ident(bad)
        for bad in ("a.b.c", "cases; DROP TABLE x", ""):
            with self.subTest(table=bad):
                with self.assertRaises(ValueError):
                    _quote_table(bad)
        self.assertEqual(_quote_table("public.cases", "`"), "`public`.`cases`")
        self.assertEqual(_quote_table("public.cases", '"'), '"public"."cases"')

    def test_host_allowed_suffix_boundary(self) -> None:
        allow = ("atlassian.net",)
        self.assertTrue(_host_allowed("acme.atlassian.net", allow))
        self.assertTrue(_host_allowed("atlassian.net", allow))
        self.assertTrue(_host_allowed("atlassian.net.", allow))
        for bad in (
            "atlassian.net.evil.com",
            "notatlassian.net",
            "evilatlassian.net",
            "box.com.attacker.io",
        ):
            with self.subTest(host=bad):
                self.assertFalse(_host_allowed(bad, allow))
        self.assertTrue(_host_allowed("api.notion.com", ("api.notion.com",)))
        self.assertFalse(_host_allowed("api.notion.com.evil", ("api.notion.com",)))

    def test_fetch_url_revalidates_redirect_and_blocks_private_target(self) -> None:
        sink: list = []
        redirect = FakeResponse(
            302, _http_headers({"Location": "http://169.254.169.254/latest/meta-data"}), b""
        )

        def fake_make_connection(scheme, host, port, pinned_ip, timeout):
            self.assertEqual(pinned_ip, host)  # IP literal is pinned for the connection
            return FakeHTTPConnection(redirect, sink)

        with patch.object(ds, "_make_connection", fake_make_connection):
            with self.assertRaises(ValueError):
                ds._fetch_url("http://93.184.216.34/start")

    def test_fetch_url_rewrites_post_to_get_on_redirect(self) -> None:
        sink: list = []
        responses = [
            FakeResponse(303, _http_headers({"Location": "http://8.8.8.8/result"}), b""),
            FakeResponse(200, _http_headers({"Content-Type": "application/json"}), b"{}"),
        ]

        def fake_make_connection(scheme, host, port, pinned_ip, timeout):
            return FakeHTTPConnection(responses.pop(0), sink)

        with patch.object(ds, "_make_connection", fake_make_connection):
            raw, content_type = ds._fetch_url(
                "http://93.184.216.34/start", data=b'{"x":1}', method="POST"
            )
        self.assertEqual(raw, b"{}")
        self.assertEqual(content_type, "text/plain")  # application/json normalized
        self.assertEqual(sink[0]["method"], "POST")
        self.assertEqual(sink[0]["body"], b'{"x":1}')
        self.assertEqual(sink[1]["method"], "GET")
        self.assertIsNone(sink[1]["body"])

    def test_fetch_url_drops_authorization_on_cross_host_redirect(self) -> None:
        sink: list = []
        responses = [
            FakeResponse(302, _http_headers({"Location": "http://8.8.8.8/file"}), b""),
            FakeResponse(200, _http_headers({"Content-Type": "text/plain"}), b"data"),
        ]

        def fake_make_connection(scheme, host, port, pinned_ip, timeout):
            return FakeHTTPConnection(responses.pop(0), sink)

        with patch.object(ds, "_make_connection", fake_make_connection):
            raw, _content_type = ds._fetch_url(
                "http://93.184.216.34/start", headers={"Authorization": "Bearer secret"}
            )
        self.assertEqual(raw, b"data")
        self.assertIn("Authorization", sink[0]["headers"])  # first hop keeps the token
        self.assertNotIn("Authorization", sink[1]["headers"])  # cross-host redirect drops it

    def test_confluence_surfaces_api_error_message(self) -> None:
        fetch = RecordingFetch(
            [
                (
                    lambda u: True,
                    (json.dumps({"message": "space not found"}).encode("utf-8"), "text/plain"),
                )
            ]
        )
        with self.assertRaises(ValueError) as ctx:
            build_sync_documents(
                "cf",
                {
                    "config": {
                        "source_type": "confluence",
                        "site_url": "https://a.atlassian.net/wiki",
                        "space_key": "X",
                        "email": "e@a.com",
                        "api_token": "t",
                    }
                },
                fetch_url=fetch,
            )
        self.assertIn("space not found", str(ctx.exception))

    def test_box_accepts_uppercase_extension_and_types_by_name(self) -> None:
        items = {
            "entries": [
                {"type": "file", "id": "f1", "name": "REPORT.XLSX"},
                {"type": "file", "id": "f2", "name": "page.HTML"},
            ]
        }
        fetch = RecordingFetch(
            [
                (lambda u: "/items" in u, (json.dumps(items).encode("utf-8"), "text/plain")),
                (lambda u: u.endswith("/content"), (b"x", "text/plain")),
            ]
        )
        docs = build_sync_documents(
            "bx",
            {"config": {"source_type": "box", "access_token": "t", "folder_id": "1"}},
            limit=10,
            fetch_url=fetch,
        )
        self.assertEqual(
            [doc.content_type for doc in docs],
            [
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "text/html",
            ],
        )

    def test_confluence_fetches_pages_with_basic_auth_and_host_allowlist(self) -> None:
        payload = {
            "results": [
                {
                    "id": "101",
                    "title": "作業手順",
                    "body": {"storage": {"value": "<p>step one</p>"}},
                    "_links": {"webui": "/spaces/MFG/pages/101"},
                },
                {
                    "id": "102",
                    "title": "点検",
                    "body": {"storage": {"value": "<p>step two</p>"}},
                    "_links": {"webui": "/spaces/MFG/pages/102"},
                },
            ]
        }
        fetch = RecordingFetch(
            [(lambda u: True, (json.dumps(payload).encode("utf-8"), "text/plain"))]
        )

        docs = build_sync_documents(
            "cf",
            {
                "config": {
                    "source_type": "confluence",
                    "site_url": "https://acme.atlassian.net/wiki",
                    "space_key": "MFG",
                    "email": "bot@acme.com",
                    "api_token": "tok",
                }
            },
            limit=10,
            fetch_url=fetch,
        )

        self.assertEqual(
            [doc.document_ref for doc in docs],
            [
                "https://acme.atlassian.net/wiki/spaces/MFG/pages/101",
                "https://acme.atlassian.net/wiki/spaces/MFG/pages/102",
            ],
        )
        self.assertEqual(docs[0].content_type, "text/html")
        self.assertIn("作業手順".encode("utf-8"), docs[0].raw)
        self.assertIn(b"step one", docs[0].raw)
        call = fetch.calls[0]
        self.assertEqual(call["allow_hosts"], ("atlassian.net",))
        self.assertTrue(call["headers"]["Authorization"].startswith("Basic "))
        decoded = base64.b64decode(call["headers"]["Authorization"].split(" ", 1)[1]).decode(
            "utf-8"
        )
        self.assertEqual(decoded, "bot@acme.com:tok")

    def test_notion_queries_database_then_expands_blocks_to_markdown(self) -> None:
        db_query = {
            "results": [
                {
                    "id": "page-1",
                    "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "乾燥工程"}]}
                    },
                },
                {
                    "id": "page-2",
                    "properties": {"Name": {"type": "title", "title": [{"plain_text": "洗浄"}]}},
                },
            ]
        }
        blocks = {
            "results": [
                {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "概要"}]}},
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "本文です"}]}},
                {
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"plain_text": "項目A"}]},
                },
                {
                    "type": "numbered_list_item",
                    "numbered_list_item": {"rich_text": [{"plain_text": "手順1"}]},
                },
                {
                    "type": "to_do",
                    "to_do": {"checked": True, "rich_text": [{"plain_text": "完了タスク"}]},
                },
                {"type": "quote", "quote": {"rich_text": [{"plain_text": "引用文"}]}},
                {
                    "type": "code",
                    "code": {"language": "python", "rich_text": [{"plain_text": "print(1)"}]},
                },
            ]
        }
        fetch = RecordingFetch(
            [
                (lambda u: "/query" in u, (json.dumps(db_query).encode("utf-8"), "text/plain")),
                (lambda u: "/blocks/" in u, (json.dumps(blocks).encode("utf-8"), "text/plain")),
            ]
        )

        docs = build_sync_documents(
            "no",
            {
                "config": {
                    "source_type": "notion",
                    "integration_token": "secret",
                    "database_id": "db123",
                }
            },
            limit=10,
            fetch_url=fetch,
        )

        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].content_type, "text/markdown")
        self.assertIn("# 乾燥工程".encode("utf-8"), docs[0].raw)
        self.assertIn("# 概要".encode("utf-8"), docs[0].raw)
        self.assertIn("- 項目A".encode("utf-8"), docs[0].raw)
        self.assertIn("1. 手順1".encode("utf-8"), docs[0].raw)
        self.assertIn("- [x] 完了タスク".encode("utf-8"), docs[0].raw)
        self.assertIn("> 引用文".encode("utf-8"), docs[0].raw)
        self.assertIn(b"```python", docs[0].raw)
        self.assertIn(b"print(1)", docs[0].raw)
        post_call = fetch.calls[0]
        self.assertEqual(post_call["method"], "POST")
        self.assertEqual(post_call["allow_hosts"], ("api.notion.com",))
        self.assertEqual(post_call["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(post_call["headers"]["Notion-Version"], "2022-06-28")
        self.assertIn(b"page_size", post_call["data"])

    def test_box_downloads_only_parseable_files(self) -> None:
        items = {
            "entries": [
                {"type": "file", "id": "f1", "name": "manual.txt"},
                {"type": "file", "id": "f2", "name": "drawing.pdf"},
                {"type": "folder", "id": "d1", "name": "sub"},
                {"type": "file", "id": "f3", "name": "notes.md"},
            ]
        }
        fetch = RecordingFetch(
            [
                (
                    lambda u: "/folders/" in u and "/items" in u,
                    (json.dumps(items).encode("utf-8"), "text/plain"),
                ),
                (lambda u: "/files/" in u and u.endswith("/content"), (b"file body", "text/plain")),
            ]
        )

        docs = build_sync_documents(
            "bx",
            {"config": {"source_type": "box", "access_token": "tok", "folder_id": "123"}},
            limit=10,
            fetch_url=fetch,
        )

        self.assertEqual(
            [doc.document_ref for doc in docs], ["box://123/manual.txt", "box://123/notes.md"]
        )
        self.assertEqual(docs[0].content_type, "text/plain")
        self.assertEqual(docs[1].content_type, "text/markdown")
        self.assertEqual(docs[0].raw, b"file body")
        list_call = fetch.calls[0]
        self.assertEqual(list_call["allow_hosts"], ("box.com", "boxcloud.com"))
        self.assertEqual(list_call["headers"]["Authorization"], "Bearer tok")

    def test_s3_custom_endpoint_requires_explicit_credentials(self) -> None:
        with patch("raku_rag.services.datasource_sync.S3Connector", FakeS3Connector):
            with self.assertRaises(ValueError):
                build_sync_documents(
                    "s3x",
                    {
                        "config": {
                            "source_type": "s3",
                            "bucket": "b",
                            "endpoint_url": "https://attacker.example",
                        }
                    },
                    limit=3,
                )

    def test_assert_public_host_blocks_private_scheme_and_allowlist(self) -> None:
        for bad in (
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://169.254.169.254/",
            "http://[::1]/",
            "http://0.0.0.0/",
            "file:///etc/passwd",
        ):
            with self.subTest(url=bad):
                with self.assertRaises(ValueError):
                    _assert_public_host(bad)
        with self.assertRaises(ValueError):
            _assert_public_host("https://evil.example/", allow_hosts=("atlassian.net",))
        # A public IP literal is allowed (no DNS needed, deterministic offline).
        _assert_public_host("http://8.8.8.8/")

    def test_gdrive_exports_native_docs_and_downloads_binaries(self) -> None:
        files = {
            "files": [
                {"id": "g1", "name": "Spec", "mimeType": "application/vnd.google-apps.document"},
                {
                    "id": "g2",
                    "name": "Budget",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                },
                {"id": "g3", "name": "diagram.png", "mimeType": "image/png"},
                {"id": "g4", "name": "readme.md", "mimeType": "text/markdown"},
                {"id": "g5", "name": "sub", "mimeType": "application/vnd.google-apps.folder"},
            ]
        }
        fetch = RecordingFetch(
            [
                (
                    lambda u: "/drive/v3/files?" in u,
                    (json.dumps(files).encode("utf-8"), "text/plain"),
                ),
                (lambda u: "/export?" in u and "g1" in u, (b"<html>doc</html>", "text/plain")),
                (lambda u: "/export?" in u and "g2" in u, (b"a,b,c", "text/plain")),
                (lambda u: "g4?" in u and "alt=media" in u, (b"# readme", "text/plain")),
            ]
        )

        docs = build_sync_documents(
            "gd",
            {"config": {"source_type": "google_drive", "folder_id": "FOLDER"}},
            body={"fresh_access_token": "fresh-tok"},
            limit=10,
            fetch_url=fetch,
        )

        # native Docs->HTML, Sheets->CSV, the .md binary; .png skipped, folder skipped
        self.assertEqual(
            [d.document_ref for d in docs],
            ["gdrive://FOLDER/Spec", "gdrive://FOLDER/Budget", "gdrive://FOLDER/readme.md"],
        )
        self.assertEqual(docs[0].content_type, "text/html")
        self.assertEqual(docs[0].raw, b"<html>doc</html>")
        self.assertEqual(docs[1].content_type, "text/csv")
        self.assertEqual(docs[2].content_type, "text/markdown")
        list_call = fetch.calls[0]
        self.assertEqual(list_call["allow_hosts"], _GDRIVE_HOSTS)
        self.assertEqual(list_call["headers"]["Authorization"], "Bearer fresh-tok")

    def test_gdrive_token_comes_from_body_not_config(self) -> None:
        files = {"files": [{"id": "g4", "name": "n.txt", "mimeType": "text/plain"}]}
        fetch = RecordingFetch(
            [
                (
                    lambda u: "/drive/v3/files?" in u,
                    (json.dumps(files).encode("utf-8"), "text/plain"),
                ),
                (lambda u: "alt=media" in u, (b"data", "text/plain")),
            ]
        )
        build_sync_documents(
            "gd",
            # a stale token sitting in config must be ignored in favour of the injected fresh one
            {"config": {"source_type": "google_drive", "access_token": "STALE", "folder_id": "F"}},
            body={"fresh_access_token": "FRESH"},
            limit=5,
            fetch_url=fetch,
        )
        self.assertEqual(fetch.calls[0]["headers"]["Authorization"], "Bearer FRESH")

    def test_gdrive_requires_oauth_token(self) -> None:
        with self.assertRaises(ValueError):
            build_sync_documents(
                "gd",
                {"config": {"source_type": "google_drive", "folder_id": "F"}},
                body={},  # no fresh_access_token -> reconnect required
                limit=5,
                fetch_url=RecordingFetch([]),
            )

    def test_gdrive_follows_pagination(self) -> None:
        page1 = {
            "files": [{"id": "a", "name": "a.txt", "mimeType": "text/plain"}],
            "nextPageToken": "TKN2",
        }
        page2 = {"files": [{"id": "b", "name": "b.txt", "mimeType": "text/plain"}]}

        def list_route(u):
            return "/drive/v3/files?" in u and "alt=media" not in u

        fetch = RecordingFetch(
            [
                (
                    lambda u: list_route(u) and "pageToken=TKN2" in u,
                    (json.dumps(page2).encode("utf-8"), "text/plain"),
                ),
                (lambda u: list_route(u), (json.dumps(page1).encode("utf-8"), "text/plain")),
                (lambda u: "alt=media" in u, (b"x", "text/plain")),
            ]
        )
        docs = build_sync_documents(
            "gd",
            {"config": {"source_type": "google_drive", "folder_id": "F"}},
            body={"fresh_access_token": "t"},
            limit=10,
            fetch_url=fetch,
        )
        self.assertEqual([d.document_ref for d in docs], ["gdrive://F/a.txt", "gdrive://F/b.txt"])
        self.assertTrue(any("pageToken=TKN2" in c["url"] for c in fetch.calls))

    def test_gdrive_parses_folder_url(self) -> None:
        files = {"files": [{"id": "a", "name": "a.txt", "mimeType": "text/plain"}]}
        fetch = RecordingFetch(
            [
                (
                    lambda u: "/drive/v3/files?" in u and "alt=media" not in u,
                    (json.dumps(files).encode("utf-8"), "text/plain"),
                ),
                (lambda u: "alt=media" in u, (b"x", "text/plain")),
            ]
        )
        build_sync_documents(
            "gd",
            {
                "config": {
                    "source_type": "google_drive",
                    "folder_id": "https://drive.google.com/drive/folders/REALID?usp=sharing",
                }
            },
            body={"fresh_access_token": "t"},
            limit=5,
            fetch_url=fetch,
        )
        self.assertIn("%27REALID%27+in+parents", fetch.calls[0]["url"])

    def test_gdrive_no_parseable_files_raises(self) -> None:
        files = {"files": [{"id": "g3", "name": "x.png", "mimeType": "image/png"}]}
        fetch = RecordingFetch(
            [(lambda u: "/drive/v3/files?" in u, (json.dumps(files).encode("utf-8"), "text/plain"))]
        )
        with self.assertRaises(ValueError):
            build_sync_documents(
                "gd",
                {"config": {"source_type": "google_drive", "folder_id": "F"}},
                body={"fresh_access_token": "t"},
                limit=5,
                fetch_url=fetch,
            )

    def test_unsupported_source_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_sync_documents("x", {"config": {"source_type": "ftp"}}, limit=1)


if __name__ == "__main__":
    unittest.main()
