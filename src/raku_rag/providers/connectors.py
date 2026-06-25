"""Connector adapters for ingestion sources."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from urllib.parse import unquote_to_bytes, urlparse

from raku_rag.interfaces.base import Connector


def _decode_data_uri(ref: str) -> bytes:
    """Decode an RFC 2397 ``data:[<mediatype>][;base64],<data>`` URI to bytes.

    Inline ``data:`` refs carry the document bytes in the ingest request itself, so ingestion works
    across process/container boundaries with NO shared filesystem or object store — the case that
    breaks ``file://`` when the uploader (web) and the answer-service run as separate containers.
    """
    if not ref.startswith("data:"):
        raise ValueError("not a data: URI")
    header, comma, data = ref[len("data:") :].partition(",")
    if not comma:
        raise ValueError("malformed data: URI (missing comma)")
    if ";base64" in header:
        # base64 may contain URL-unsafe chars only if percent-encoded; decode defensively.
        return base64.b64decode(unquote_to_bytes(data))
    return unquote_to_bytes(data)


class DataUriConnector(Connector):
    """Resolves inline ``data:`` refs itself; delegates every other ref to an inner connector.

    Wrapping the env-selected connector (file/S3) means the Add-Source upload and the demo seed can
    hand the answer-service document bytes inline (``data:`` ref) regardless of the backing store,
    while ``s3://`` / ``file://`` refs still flow through to the inner connector unchanged.
    """

    def __init__(self, inner: Connector) -> None:
        self.inner = inner

    def fetch(self, ref: str) -> bytes:
        if ref.startswith("data:"):
            return _decode_data_uri(ref)
        return self.inner.fetch(ref)

    def __getattr__(self, name: str):
        # Transparently expose inner-only members (e.g. S3Connector.list_refs, MemoryConnector.put).
        return getattr(self.inner, name)


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
    endpoint_url: str | None = None
    region_name: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            try:
                import boto3  # type: ignore
            except Exception as exc:  # pragma: no cover - optional prod dependency
                raise RuntimeError(
                    "boto3 is required for S3Connector without an injected client"
                ) from exc
            endpoint_url = (
                self.endpoint_url
                or os.environ.get("S3_ENDPOINT_URL")
                or os.environ.get("AWS_ENDPOINT_URL")
            )
            region_name = self.region_name or os.environ.get("AWS_REGION", "us-east-1")
            access_key = self.access_key_id or os.environ.get("S3_ACCESS_KEY")
            secret_key = self.secret_access_key or os.environ.get("S3_SECRET_KEY")
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

    def list_refs(self, *, prefix: str = "", limit: int = 25) -> list[str]:
        bucket = self.bucket or ""
        if not bucket:
            raise ValueError("S3 list requires a default bucket")
        if limit <= 0:
            return []
        assert self.client is not None
        refs: list[str] = []
        kwargs: dict[str, object] = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxKeys": min(limit, 1000),
        }
        while len(refs) < limit:
            response = self.client.list_objects_v2(**kwargs)
            for item in response.get("Contents", []):
                key = str(item.get("Key") or "")
                if key and not key.endswith("/"):
                    refs.append(f"s3://{bucket}/{key}")
                    if len(refs) >= limit:
                        break
            token = response.get("NextContinuationToken")
            if not response.get("IsTruncated") or not token or len(refs) >= limit:
                break
            kwargs["ContinuationToken"] = token
        return refs

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
        inner: Connector = S3Connector(bucket=os.environ.get("S3_BUCKET"))
    else:
        inner = FileConnector()
    # Always accept inline data: refs on top of the configured store, so an uploader in a different
    # container than the answer-service can ingest without a shared filesystem / object store.
    return DataUriConnector(inner)
