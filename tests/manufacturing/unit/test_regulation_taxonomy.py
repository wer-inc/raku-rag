import unittest

from raku_rag.manufacturing.domain.metadata import (
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.domain.regulations import (
    REGULATION_CATALOG,
    infer_regulation_refs,
    validate_regulation_refs,
)


class TestRegulationTaxonomy(unittest.TestCase):
    def test_metadata_round_trip_preserves_explicit_regulation_refs(self) -> None:
        meta = ManufacturingDocumentMetadata(
            tenant_id="t1",
            document_id="d1",
            regulation_refs=("ISO_12100_2010", "JIS_B_9700_2013"),
        )

        restored = ManufacturingDocumentMetadata.from_mapping(meta.to_mapping())

        self.assertEqual(restored.regulation_refs, ("ISO_12100_2010", "JIS_B_9700_2013"))

    def test_safety_machine_and_electrical_tags_infer_review_anchors(self) -> None:
        meta = ManufacturingDocumentMetadata(
            tenant_id="t1",
            document_id="lockout",
            document_kind=DocumentKind.WORK_INSTRUCTION,
            safety_category="lockout_tagout",
            hazard_tags=("設備停止", "分解", "高圧", "safety_device"),
        )

        refs = infer_regulation_refs(meta)

        self.assertIn("JP_ISHA", refs)
        self.assertIn("JP_ISH_RULES", refs)
        self.assertIn("ISO_45001_2018", refs)
        self.assertIn("ISO_12100_2010", refs)
        self.assertIn("JIS_B_9700_2013", refs)
        self.assertIn("JIS_B_9960_1_2019", refs)
        self.assertIn("ISO_13849_1_2023", refs)

    def test_quality_document_infers_iso_9001(self) -> None:
        meta = ManufacturingDocumentMetadata(
            tenant_id="t1",
            document_id="quality",
            document_kind=DocumentKind.QUALITY_REPORT,
        )

        self.assertEqual(infer_regulation_refs(meta), ("ISO_9001_2015",))

    def test_unknown_regulation_ref_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_regulation_refs(("NOT_A_STANDARD",))

    def test_catalog_entries_have_source_urls(self) -> None:
        required = {
            "ISO_9001_2015",
            "ISO_45001_2018",
            "ISO_12100_2010",
            "JIS_B_9700_2013",
            "JP_ISHA",
            "JP_ISH_RULES",
        }

        self.assertTrue(required.issubset(REGULATION_CATALOG))
        for ref_id in required:
            self.assertTrue(REGULATION_CATALOG[ref_id].source_url.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
