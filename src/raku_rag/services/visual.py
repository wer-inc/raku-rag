"""US6 visual RAG helpers."""

from __future__ import annotations

from raku_rag.domain.models import Chunk, LayoutRegion, Modality
from raku_rag.workers.ingestion import VisualIngestionResult


def visual_chunk_text(region: LayoutRegion) -> str:
    parts = [region.ocr_text.strip()]
    if region.generated_caption_text:
        # Caption is retrieval aid only. Answer generation reads primary_evidence_text from metadata.
        parts.append(region.generated_caption_text.strip())
    return "\n".join(part for part in parts if part)


def visual_chunks_from_ingestion(result: VisualIngestionResult) -> tuple[Chunk, ...]:
    chunks: list[Chunk] = []
    for idx, region in enumerate(result.regions):
        text = visual_chunk_text(region)
        redaction_metadata = _visual_redaction_metadata(region)
        chunks.append(
            Chunk(
                tenant_id=region.tenant_id,
                chunk_id=f"{region.document_id}:visual:{idx}",
                document_id=region.document_id,
                collection_id=region.collection_id,
                text=text,
                position=idx,
                token_count=len(text.split()),
                heading_path=region.heading_path,
                modality=Modality.VISUAL,
                embedding_model_version=result.asset.metadata.get(
                    "visual_embedding_model_version", ""
                ),
                metadata={
                    "asset_id": region.asset_id,
                    "region_id": region.region_id,
                    "page_number": region.page_number,
                    "bbox": {
                        "x": region.bbox.x,
                        "y": region.bbox.y,
                        "width": region.bbox.width,
                        "height": region.bbox.height,
                    },
                    "crop_uri": region.crop_uri,
                    "region_type": region.region_type,
                    "ocr_text": region.ocr_text,
                    "generated_caption_text": region.generated_caption_text,
                    "primary_evidence_text": region.ocr_text,
                    **redaction_metadata,
                },
            )
        )
    return tuple(chunks)


def _visual_redaction_metadata(region: LayoutRegion) -> dict:
    labels = region.metadata.get("sensitive_detection_labels") or []
    if not isinstance(labels, list):
        labels = list(labels) if isinstance(labels, tuple) else []
    sensitive_detected = bool(region.metadata.get("sensitive_detected") or labels)
    return {
        "sensitive_detected": sensitive_detected,
        "sensitive_detection_labels": sorted(str(label) for label in labels),
        "pii_redaction_applied": bool(region.metadata.get("pii_redaction_applied")),
        "secret_redaction_applied": bool(region.metadata.get("secret_redaction_applied")),
        "pii_redaction_policy_ref": str(region.metadata.get("pii_redaction_policy_ref") or ""),
        "visual_region_redaction_required": bool(
            region.metadata.get("visual_region_redaction_required") or sensitive_detected
        ),
        "visual_region_redaction_status": str(
            region.metadata.get("visual_region_redaction_status") or "not_required"
        ),
        "visual_redaction_policy_ref": str(
            region.metadata.get("visual_redaction_policy_ref") or ""
        ),
    }
