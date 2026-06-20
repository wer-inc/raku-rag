"""Connector adapters for ingestion sources."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

from raku_rag.interfaces.base import Connector


class FileConnector(Connector):
    """Fetch bytes from a local file path or ``file://`` URL.

    This is the deterministic local adapter used by the production-track worker tests. S3/MinIO
    adapters can share the same ``Connector.fetch(ref)`` seam.
    """

    def fetch(self, ref: str) -> bytes:
        path = ref[7:] if ref.startswith("file://") else ref
        with open(path, "rb") as fh:
            return fh.read()


@dataclass
class MemoryConnector(Connector):
    """In-memory object store useful for queue/worker tests."""

    objects: dict[str, bytes] = field(default_factory=dict)

    def put(self, ref: str, raw: bytes) -> str:
        self.objects[ref] = bytes(raw)
        return ref

    def fetch(self, ref: str) -> bytes:
        if ref not in self.objects:
            raise FileNotFoundError(ref)
        return self.objects[ref]


@dataclass
class S3Connector(Connector):
    """S3/MinIO-compatible object connector.

    ``ref`` may be ``s3://bucket/key`` or just ``key`` when ``bucket`` is configured. A client can be
    injected in tests; otherwise boto3 is created lazily using S3 endpoint env vars for MinIO.
    """

    bucket: str | None = None
    client: object | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            try:
                import boto3  # type: ignore
            except Exception as exc:  # pragma: no cover - optional prod dependency
                raise RuntimeError(
                    "boto3 is required for S3Connector without an injected client"
                ) from exc
            endpoint_url = os.environ.get("S3_ENDPOINT_URL") or os.environ.get("AWS_ENDPOINT_URL")
            region_name = os.environ.get("AWS_REGION", "us-east-1")
            access_key = os.environ.get("S3_ACCESS_KEY")
            secret_key = os.environ.get("S3_SECRET_KEY")
            kwargs = {"endpoint_url": endpoint_url, "region_name": region_name}
            if access_key and secret_key:
                kwargs["aws_access_key_id"] = access_key
                kwargs["aws_secret_access_key"] = secret_key
            self.client = boto3.client("s3", **kwargs)

    def fetch(self, ref: str) -> bytes:
        bucket, key = self._parse_ref(ref)
        assert self.client is not None
        obj = self.client.get_object(Bucket=bucket, Key=key)
        body = obj["Body"]
        return body.read()

    def _parse_ref(self, ref: str) -> tuple[str, str]:
        if ref.startswith("s3://"):
            parsed = urlparse(ref)
            bucket = parsed.netloc
            key = parsed.path.lstrip("/")
        else:
            bucket = self.bucket or ""
            key = ref
        if not bucket or not key:
            raise ValueError("S3 ref must include bucket and key")
        return bucket, key


def default_connector_from_env() -> Connector:
    if os.environ.get("RAKU_INGEST_CONNECTOR") == "s3" or os.environ.get("S3_BUCKET"):
        return S3Connector(bucket=os.environ.get("S3_BUCKET"))
    return FileConnector()
