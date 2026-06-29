"""Connector contracts for local file and S3/MinIO-compatible ingestion refs."""

from __future__ import annotations

import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from raku_rag.providers.connectors import (
    DataUriConnector,
    FileConnector,
    S3Connector,
    default_connector_from_env,
)


class FakeS3Client:
    def __init__(
        self,
        objects: dict[tuple[str, str], bytes],
        metadata: dict[tuple[str, str], dict[str, str]] | None = None,
    ) -> None:
        self.objects = objects
        self.metadata = metadata or {}
        self.requests: list[dict] = []
        self.head_requests: list[dict] = []
        self.list_requests: list[dict] = []
        self.put_requests: list[dict] = []
        self.presign_requests: list[dict] = []

    def get_object(self, **kwargs):
        self.requests.append(kwargs)
        key = (kwargs["Bucket"], kwargs["Key"])
        if key not in self.objects:
            raise FileNotFoundError(key)
        return {"Body": io.BytesIO(self.objects[key])}

    def head_object(self, **kwargs):
        self.head_requests.append(kwargs)
        key = (kwargs["Bucket"], kwargs["Key"])
        if key not in self.objects:
            raise FileNotFoundError(key)
        return {
            "ContentLength": len(self.objects[key]),
            "Metadata": self.metadata.get(key, {}),
        }

    def list_objects_v2(self, **kwargs):
        self.list_requests.append(kwargs)
        bucket = kwargs["Bucket"]
        prefix = kwargs.get("Prefix") or ""
        contents = [
            {"Key": key}
            for obj_bucket, key in sorted(self.objects)
            if obj_bucket == bucket and key.startswith(prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}

    def put_object(self, **kwargs):
        self.put_requests.append(kwargs)
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = bytes(kwargs["Body"])
        self.metadata[(kwargs["Bucket"], kwargs["Key"])] = dict(kwargs.get("Metadata") or {})
        return {"ETag": "etag"}

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.presign_requests.append(
            {"operation": operation, "Params": Params, "ExpiresIn": ExpiresIn}
        )
        return f"https://signed.example/{Params['Bucket']}/{Params['Key']}?ttl={ExpiresIn}"


class TestConnectors(unittest.TestCase):
    def test_file_connector_fetches_path_and_file_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.txt"
            path.write_bytes(b"hello file")
            connector = FileConnector()
            self.assertEqual(connector.fetch(str(path)), b"hello file")
            self.assertEqual(connector.fetch(f"file://{path}"), b"hello file")

    def test_s3_connector_fetches_s3_url(self) -> None:
        client = FakeS3Client({("docs", "a/b.txt"): b"hello s3"})
        connector = S3Connector(client=client)

        self.assertEqual(connector.fetch("s3://docs/a/b.txt"), b"hello s3")
        self.assertEqual(client.requests[0], {"Bucket": "docs", "Key": "a/b.txt"})

    def test_s3_connector_fetches_key_with_default_bucket(self) -> None:
        client = FakeS3Client({("default", "doc.txt"): b"default bucket"})
        connector = S3Connector(bucket="default", client=client)

        self.assertEqual(connector.fetch("doc.txt"), b"default bucket")

    def test_s3_connector_requires_bucket_and_key(self) -> None:
        connector = S3Connector(client=FakeS3Client({}))
        with self.assertRaises(ValueError):
            connector.fetch("missing-bucket-key")

    def test_s3_connector_lists_refs_by_prefix(self) -> None:
        client = FakeS3Client(
            {
                ("docs", "manuals/a.txt"): b"a",
                ("docs", "manuals/b.txt"): b"b",
                ("docs", "other/c.txt"): b"c",
            }
        )
        connector = S3Connector(bucket="docs", client=client)

        self.assertEqual(
            connector.list_refs(prefix="manuals/", limit=10),
            ["s3://docs/manuals/a.txt", "s3://docs/manuals/b.txt"],
        )

    def test_s3_connector_puts_bytes_and_presigns_gets(self) -> None:
        client = FakeS3Client({})
        connector = S3Connector(bucket="docs", client=client)

        ref = connector.put_bytes("uploads/doc.pdf", b"%PDF", content_type="application/pdf")
        url = connector.presigned_get_url(ref, expires_in=120)

        self.assertEqual(ref, "s3://docs/uploads/doc.pdf")
        self.assertEqual(client.objects[("docs", "uploads/doc.pdf")], b"%PDF")
        self.assertEqual(client.put_requests[0]["ContentType"], "application/pdf")
        self.assertEqual(url, "https://signed.example/docs/uploads/doc.pdf?ttl=120")

    def test_s3_connector_reads_object_info(self) -> None:
        client = FakeS3Client(
            {("docs", "uploads/doc.txt"): b"hello"},
            metadata={("docs", "uploads/doc.txt"): {"Raku-Tenant-Id": "tenant_a"}},
        )
        connector = S3Connector(bucket="docs", client=client)

        info = connector.object_info("s3://docs/uploads/doc.txt")

        self.assertEqual(info["bucket"], "docs")
        self.assertEqual(info["key"], "uploads/doc.txt")
        self.assertEqual(info["content_length"], 5)
        self.assertEqual(info["metadata"], {"raku-tenant-id": "tenant_a"})
        self.assertEqual(client.head_requests[0], {"Bucket": "docs", "Key": "uploads/doc.txt"})


class TestDataUriConnector(unittest.TestCase):
    def test_decodes_base64_data_uri(self) -> None:
        raw = "圧入トルク 12N·m".encode("utf-8")
        ref = "data:text/plain;base64," + base64.b64encode(raw).decode("ascii")
        connector = DataUriConnector(FileConnector())
        self.assertEqual(connector.fetch(ref), raw)

    def test_decodes_plain_percent_encoded_data_uri(self) -> None:
        connector = DataUriConnector(FileConnector())
        self.assertEqual(connector.fetch("data:text/plain,hello%20world"), b"hello world")

    def test_delegates_non_data_refs_to_inner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.txt"
            path.write_bytes(b"hello file")
            connector = DataUriConnector(FileConnector())
            self.assertEqual(connector.fetch(f"file://{path}"), b"hello file")

    def test_passthrough_inner_only_members(self) -> None:
        # __getattr__ must expose inner-only attributes (e.g. S3Connector.list_refs).
        client = FakeS3Client({("docs", "m/a.txt"): b"a"})
        connector = DataUriConnector(S3Connector(bucket="docs", client=client))
        self.assertEqual(connector.list_refs(prefix="m/", limit=5), ["s3://docs/m/a.txt"])

    def test_default_connector_from_env_wraps_with_data_uri_support(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            connector = default_connector_from_env()
        self.assertIsInstance(connector, DataUriConnector)
        self.assertIsInstance(connector.inner, FileConnector)
        ref = "data:text/plain;base64," + base64.b64encode(b"inline").decode("ascii")
        self.assertEqual(connector.fetch(ref), b"inline")


if __name__ == "__main__":
    unittest.main()
