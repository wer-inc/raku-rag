"""ADR-018 A4 §P2 — raw provider-output sinks."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from raku_rag.services.raw_sink import (
    FilesystemRawSink,
    NoOpRawSink,
    S3RawSink,
    build_raw_sink,
)


class RawSinkTest(unittest.TestCase):
    def test_filesystem_sink_writes_json_per_document(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sink = FilesystemRawSink(d)
            sink("doc/../weird id", {"schema_version": "parsed_document.v1", "blocks": []})
            files = os.listdir(d)
            self.assertEqual(len(files), 1)
            with open(os.path.join(d, files[0]), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["schema_version"], "parsed_document.v1")

    def test_noop_sink_does_nothing(self) -> None:
        NoOpRawSink()("d", {"x": 1})  # no exception, no output

    def test_build_raw_sink_default_is_none(self) -> None:
        self.assertIsNone(build_raw_sink({}))
        self.assertIsNone(build_raw_sink({"RAKU_RAW_SINK": "none"}))

    def test_build_raw_sink_fs(self) -> None:
        sink = build_raw_sink({"RAKU_RAW_SINK": "fs", "RAKU_RAW_SINK_DIR": "/tmp/x"})
        self.assertIsInstance(sink, FilesystemRawSink)

    def test_build_raw_sink_s3_requires_bucket(self) -> None:
        self.assertIsNone(build_raw_sink({"RAKU_RAW_SINK": "s3"}))
        sink = build_raw_sink({"RAKU_RAW_SINK": "s3", "RAKU_RAW_SINK_S3_BUCKET": "b"})
        self.assertIsInstance(sink, S3RawSink)

    def test_s3_sink_uses_injected_client(self) -> None:
        class _FakeS3:
            def __init__(self) -> None:
                self.calls = []

            def put_object(self, **kw) -> None:
                self.calls.append(kw)

        fake = _FakeS3()
        S3RawSink("bucket", client=fake)("doc1", {"a": 1})
        self.assertEqual(fake.calls[0]["Bucket"], "bucket")
        self.assertEqual(fake.calls[0]["Key"], "raw-parsed/doc1.json")


if __name__ == "__main__":
    unittest.main()
