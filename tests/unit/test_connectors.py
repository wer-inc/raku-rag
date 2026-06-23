"""Connector contracts for local file and S3/MinIO-compatible ingestion refs."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from raku_rag.providers.connectors import FileConnector, S3Connector


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


if __name__ == "__main__":
    unittest.main()
