"""ADR-018 §P2 — sinks for raw provider output (e.g. DoclingDocument) for reproducibility / audit.

The StructuredIngestionService hands its ParsedDocument.to_dict() (the raw normalized provider output)
to a ``raw_sink`` callable. Default is a no-op; production selects a Filesystem or S3 sink by config.
S3 is opt-in (lazy boto3). PII/retention policy for stored raw output is governed separately (§19).
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

RAW_SINK_ENV = "RAKU_RAW_SINK"  # none | fs | s3
RAW_SINK_DIR_ENV = "RAKU_RAW_SINK_DIR"
RAW_SINK_S3_BUCKET_ENV = "RAKU_RAW_SINK_S3_BUCKET"
RAW_SINK_S3_PREFIX_ENV = "RAKU_RAW_SINK_S3_PREFIX"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(document_id: str) -> str:
    return _UNSAFE.sub("_", document_id or "doc") or "doc"


class RawSink(Protocol):
    def __call__(self, document_id: str, raw: dict) -> None: ...


class NoOpRawSink:
    def __call__(self, document_id: str, raw: dict) -> None:
        return None


class FilesystemRawSink:
    """Write raw output as one JSON file per document (local/dev; deterministic + testable)."""

    def __init__(self, directory: str) -> None:
        self._dir = directory

    def __call__(self, document_id: str, raw: dict) -> None:
        os.makedirs(self._dir, exist_ok=True)
        path = os.path.join(self._dir, f"{_safe_name(document_id)}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh, ensure_ascii=False)


class S3RawSink:
    """Persist raw output to S3 (production, §P2). Lazy boto3 — opt-in, not imported by the gate."""

    def __init__(
        self, bucket: str, *, prefix: str = "raw-parsed/", client: object | None = None
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix
        self._client = client

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client

    def __call__(self, document_id: str, raw: dict) -> None:
        key = f"{self._prefix}{_safe_name(document_id)}.json"
        body = json.dumps(raw, ensure_ascii=False).encode("utf-8")
        self._get_client().put_object(
            Bucket=self._bucket, Key=key, Body=body, ContentType="application/json"
        )


def build_raw_sink(env: dict | None = None) -> RawSink | None:
    """Select a raw sink from env: RAKU_RAW_SINK=fs|s3|none (default none => None)."""

    env = env if env is not None else os.environ
    kind = (env.get(RAW_SINK_ENV) or "none").strip().lower()
    if kind == "fs":
        return FilesystemRawSink(env.get(RAW_SINK_DIR_ENV) or "./raw-parsed")
    if kind == "s3":
        bucket = env.get(RAW_SINK_S3_BUCKET_ENV)
        if not bucket:
            return None
        return S3RawSink(bucket, prefix=env.get(RAW_SINK_S3_PREFIX_ENV) or "raw-parsed/")
    return None
