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
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects
        self.requests: list[dict] = []
        self.list_requests: list[dict] = []

    def get_object(self, **kwargs):
        self.requests.append(kwargs)
        key = (kwargs["Bucket"], kwargs["Key"])
        if key not in self.objects:
            raise FileNotFoundError(key)
        return {"Body": io.BytesIO(self.objects[key])}

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
