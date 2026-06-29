"""T074 - visual crop generation with inheritance rules."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from io import BytesIO
from urllib.parse import urlparse

from raku_rag.core.config import Settings
from raku_rag.domain.models import CropArtifact, LayoutRegion
from raku_rag.providers.connectors import S3Connector

REDACTED_CROP_URI_PREFIX = "memory://redacted-crops"
VISUAL_REGION_REDACTION_REQUIRED_REF = "visual-region-redaction-required"
_EMPTY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax"
    "jP4YAAAAASUVORK5CYII="
)


@dataclass
class InMemoryCropStore:
    _crops: dict[tuple[str, str], CropArtifact] = field(default_factory=dict)

    def put(self, crop: CropArtifact) -> CropArtifact:
        self._crops[(crop.tenant_id, crop.crop_id)] = crop
        return crop

    def get(self, tenant_id: str, crop_id: str) -> CropArtifact | None:
        crop = self._crops.get((tenant_id, crop_id))
        if crop is None or crop.tombstone:
            return None
        return crop

    def list_document(self, tenant_id: str, document_id: str) -> tuple[CropArtifact, ...]:
        return tuple(
            crop
            for (t, _), crop in self._crops.items()
            if t == tenant_id and crop.document_id == document_id and not crop.tombstone
        )

    def tombstone_document(self, tenant_id: str, document_id: str) -> int:
        count = 0
        for (t, _), crop in self._crops.items():
            if t == tenant_id and crop.document_id == document_id and not crop.tombstone:
                crop.tombstone = True
                count += 1
        return count


class S3CropStore(InMemoryCropStore):
    """Metadata store plus S3 object materialization for rendered crops."""

    def __init__(
        self,
        storage_uri: str,
        *,
        connector: S3Connector | None = None,
        presign_expires_in: int = 300,
    ) -> None:
        super().__init__()
        parsed = urlparse(storage_uri)
        if parsed.scheme != "s3" or not parsed.netloc:
            raise ValueError("S3CropStore requires s3://bucket[/prefix]")
        self.bucket = parsed.netloc
        self.prefix = parsed.path.strip("/")
        self.connector = connector or S3Connector(bucket=self.bucket)
        self.presign_expires_in = presign_expires_in

    def uri_for(self, region: LayoutRegion, crop_id: str, *, redacted: bool = False) -> str:
        parts = [
            self.prefix,
            _safe_key_part(region.tenant_id),
            _safe_key_part(region.collection_id),
            _safe_key_part(region.document_id),
        ]
        filename = f"{_safe_key_part(crop_id)}.png"
        if redacted:
            filename = f"redacted-{filename}"
        key = "/".join(part for part in (*parts, filename) if part)
        return f"s3://{self.bucket}/{key}"

    def put_crop_bytes(
        self,
        crop: CropArtifact,
        *,
        raw_bytes: bytes = b"",
        redacted_bytes: bytes | None = None,
        content_type: str = "image/png",
    ) -> None:
        self._put_uri(crop.crop_uri, raw_bytes or _EMPTY_PNG, content_type=content_type)
        redacted_uri = str(crop.metadata.get("redacted_crop_uri") or "")
        if redacted_uri:
            self._put_uri(
                redacted_uri,
                redacted_bytes if redacted_bytes is not None else raw_bytes or _EMPTY_PNG,
                content_type=content_type,
            )

    def public_url(self, uri: str) -> str:
        return self.connector.presigned_get_url(uri, expires_in=self.presign_expires_in)

    def _put_uri(self, uri: str, raw: bytes, *, content_type: str) -> None:
        parsed = urlparse(uri)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError("crop uri must be an s3://bucket/key URI")
        self.connector.put_bytes(
            parsed.path.lstrip("/"),
            raw,
            content_type=content_type,
            bucket=parsed.netloc,
        )


class CropService:
    def __init__(self, store: InMemoryCropStore | None = None) -> None:
        self.store = store or InMemoryCropStore()

    def create_region_crop(
        self,
        region: LayoutRegion,
        *,
        redaction_policy_ref: str = "inherit",
        raw_bytes: bytes = b"",
        redacted_bytes: bytes | None = None,
        content_type: str = "image/png",
    ) -> CropArtifact:
        crop_id = f"crop:{region.asset_id}:{region.region_id}"
        labels = _sensitive_labels(region)
        redaction_required = bool(
            region.metadata.get("visual_region_redaction_required")
            or region.metadata.get("sensitive_detected")
            or labels
        )
        effective_redaction_ref = (
            VISUAL_REGION_REDACTION_REQUIRED_REF
            if redaction_policy_ref == "inherit" and redaction_required
            else redaction_policy_ref
        )
        raw_crop_uri = _raw_crop_uri(self.store, region, crop_id)
        redacted_crop_uri = (
            _redacted_crop_uri_for_store(self.store, region, crop_id) if redaction_required else ""
        )
        crop = CropArtifact(
            tenant_id=region.tenant_id,
            collection_id=region.collection_id,
            document_id=region.document_id,
            asset_id=region.asset_id,
            region_id=region.region_id,
            crop_id=crop_id,
            bbox=region.bbox,
            crop_uri=raw_crop_uri,
            redaction_policy_ref=effective_redaction_ref,
            metadata={
                "inherits_acl_from_document_id": region.document_id,
                "inherits_redaction_from_region_id": region.region_id,
                "source_page_number": region.page_number,
                "raw_crop_uri": raw_crop_uri,
                "redacted_crop_uri": redacted_crop_uri,
                "crop_content_type": content_type,
                "sensitive_detected": bool(region.metadata.get("sensitive_detected") or labels),
                "sensitive_detection_labels": labels,
                "pii_redaction_policy_ref": str(
                    region.metadata.get("pii_redaction_policy_ref") or ""
                ),
                "visual_region_redaction_required": redaction_required,
                "visual_region_redaction_status": (
                    "required" if redaction_required else "not_required"
                ),
            },
            tombstone=region.tombstone,
        )
        rendered_raw = _render_crop_bytes(raw_bytes, region, content_type=content_type)
        rendered_redacted = (
            _render_crop_bytes(redacted_bytes, region, content_type=content_type)
            if redacted_bytes is not None
            else None
        )
        crop.metadata["crop_render_status"] = "rendered" if rendered_raw else "not_rendered"
        stored = self.store.put(crop)
        if hasattr(self.store, "put_crop_bytes"):
            self.store.put_crop_bytes(  # type: ignore[attr-defined]
                stored,
                raw_bytes=rendered_raw,
                redacted_bytes=rendered_redacted,
                content_type=content_type,
            )
        return stored

    def get_authorized_crop(
        self, tenant_id: str, crop_id: str, *, document_visible: bool
    ) -> CropArtifact | None:
        if not document_visible:
            return None
        return self.store.get(tenant_id, crop_id)


def _sensitive_labels(region: LayoutRegion) -> list[str]:
    labels = region.metadata.get("sensitive_detection_labels") or []
    if isinstance(labels, tuple):
        labels = list(labels)
    if not isinstance(labels, list):
        return []
    return sorted(str(label) for label in labels)


def _redacted_crop_uri(tenant_id: str, crop_id: str) -> str:
    return f"{REDACTED_CROP_URI_PREFIX}/{tenant_id}/{crop_id}"


def _raw_crop_uri(store: InMemoryCropStore, region: LayoutRegion, crop_id: str) -> str:
    if hasattr(store, "uri_for"):
        return str(store.uri_for(region, crop_id, redacted=False))  # type: ignore[attr-defined]
    return f"memory://crops/{region.tenant_id}/{crop_id}"


def _redacted_crop_uri_for_store(
    store: InMemoryCropStore, region: LayoutRegion, crop_id: str
) -> str:
    if hasattr(store, "uri_for"):
        return str(store.uri_for(region, crop_id, redacted=True))  # type: ignore[attr-defined]
    return _redacted_crop_uri(region.tenant_id, crop_id)


def _safe_key_part(value: object) -> str:
    text = str(value or "")
    return "".join(ch if ch.isalnum() or ch in "._=-" else "-" for ch in text).strip("-")


def _render_crop_bytes(raw: bytes | None, region: LayoutRegion, *, content_type: str) -> bytes:
    if not raw:
        return b""
    try:
        from PIL import Image  # type: ignore
    except Exception:  # pragma: no cover - optional production dependency
        return bytes(raw)
    try:
        with Image.open(BytesIO(raw)) as image:
            width, height = image.size
            left, upper, right, lower = _pixel_box(region, width=width, height=height)
            cropped = image.crop((left, upper, right, lower))
            output = BytesIO()
            cropped.save(output, format="PNG")
            return output.getvalue()
    except Exception:
        return bytes(raw)


def _pixel_box(region: LayoutRegion, *, width: int, height: int) -> tuple[int, int, int, int]:
    bbox = region.bbox
    left = int(max(0.0, min(1.0, bbox.x)) * width)
    upper = int(max(0.0, min(1.0, bbox.y)) * height)
    right = int(max(0.0, min(1.0, bbox.x + bbox.width)) * width)
    lower = int(max(0.0, min(1.0, bbox.y + bbox.height)) * height)
    if right <= left:
        right = min(width, left + 1)
    if lower <= upper:
        lower = min(height, upper + 1)
    return left, upper, right, lower


def crop_service_from_settings(settings: Settings) -> CropService:
    if settings.crop_storage_uri.strip().startswith("s3://"):
        return CropService(S3CropStore(settings.crop_storage_uri.strip()))
    return CropService()


__all__ = ["CropService", "InMemoryCropStore", "S3CropStore", "crop_service_from_settings"]
