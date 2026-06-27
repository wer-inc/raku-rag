from __future__ import annotations

import unittest
from dataclasses import replace

from raku_rag.core.config import Settings
from raku_rag.domain.models import BoundingBox, LayoutRegion
from raku_rag.manufacturing.safety.visual_verify import (
    StaticVisualEvidenceVerifier,
    verify_visual_primary_evidence,
)


def _region(
    *,
    ocr_text: str = "Pump panel shows alarm AL-42.",
    caption: str = "Caption says alarm AL-42.",
    crop_uri: str = "s3://visual-crops/tenant/doc/region.png",
) -> LayoutRegion:
    return LayoutRegion(
        tenant_id="tenant_a",
        collection_id="manuals",
        document_id="doc_visual",
        asset_id="asset_1",
        region_id="region_1",
        bbox=BoundingBox(0.0, 0.0, 1.0, 0.2),
        ocr_text=ocr_text,
        generated_caption_text=caption,
        crop_uri=crop_uri,
    )


class VisualEvidenceVerifierTest(unittest.TestCase):
    def test_promotes_only_with_ocr_subset_and_distinct_vlm_quorum(self) -> None:
        verified, verdicts = verify_visual_primary_evidence(
            assertion="Pump panel shows alarm AL-42.",
            region=_region(),
            verifiers=(
                StaticVisualEvidenceVerifier("bedrock_claude", "bedrock", "claude-sonnet"),
                StaticVisualEvidenceVerifier("vertex_gemini", "vertex", "gemini-pro"),
            ),
            settings=Settings(visual_evidence_promotion=True),
        )

        self.assertTrue(verified)
        self.assertEqual([v.reason_code for v in verdicts], ["substring_match", "match", "match"])

    def test_caption_without_ocr_never_promotes(self) -> None:
        verified, verdicts = verify_visual_primary_evidence(
            assertion="Caption says alarm AL-42.",
            region=_region(ocr_text="", caption="Caption says alarm AL-42."),
            verifiers=(
                StaticVisualEvidenceVerifier("bedrock_claude", "bedrock", "claude-sonnet"),
                StaticVisualEvidenceVerifier("vertex_gemini", "vertex", "gemini-pro"),
            ),
            settings=Settings(visual_evidence_promotion=True),
        )

        self.assertFalse(verified)
        self.assertEqual(verdicts[0].reason_code, "ocr_empty")

    def test_real_crop_is_required_before_vlm_quorum(self) -> None:
        verified, verdicts = verify_visual_primary_evidence(
            assertion="Pump panel shows alarm AL-42.",
            region=_region(crop_uri="memory://crops/tenant/doc/region.png"),
            verifiers=(
                StaticVisualEvidenceVerifier("bedrock_claude", "bedrock", "claude-sonnet"),
                StaticVisualEvidenceVerifier("vertex_gemini", "vertex", "gemini-pro"),
            ),
            settings=Settings(visual_evidence_promotion=True),
        )

        self.assertFalse(verified)
        self.assertEqual(verdicts[-1].reason_code, "real_crop_required")

    def test_same_family_models_do_not_satisfy_quorum_by_default(self) -> None:
        settings = Settings(visual_evidence_promotion=True)
        verifiers = (
            StaticVisualEvidenceVerifier("bedrock_claude_sonnet", "bedrock", "claude-sonnet"),
            StaticVisualEvidenceVerifier("bedrock_claude_haiku", "bedrock", "claude-haiku"),
        )

        verified, verdicts = verify_visual_primary_evidence(
            assertion="Pump panel shows alarm AL-42.",
            region=_region(),
            verifiers=verifiers,
            settings=settings,
        )
        self.assertFalse(verified)
        self.assertEqual(verdicts[-1].reason_code, "distinct_provider_quorum_not_met")

        verified_with_attestation, _ = verify_visual_primary_evidence(
            assertion="Pump panel shows alarm AL-42.",
            region=_region(),
            verifiers=verifiers,
            settings=replace(settings, visual_verifier_allow_same_family_distinct_models=True),
        )
        self.assertTrue(verified_with_attestation)


if __name__ == "__main__":
    unittest.main()
