from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RetrievalProfileContractTest(unittest.TestCase):
    def test_dedicated_api_controller_and_service_are_present(self) -> None:
        controller = (ROOT / "apps/api/src/admin/retrieval-profiles.controller.ts").read_text(
            encoding="utf-8"
        )
        service = (ROOT / "apps/api/src/retrieval/retrieval-profile.service.ts").read_text(
            encoding="utf-8"
        )
        app_module = (ROOT / "apps/api/src/app.module.ts").read_text(encoding="utf-8")

        self.assertIn('@Controller({ path: "admin/retrieval-profiles", version: "1" })', controller)
        self.assertIn("RetrievalProfileService", service)
        self.assertIn("RetrievalProfilesController", app_module)
        self.assertIn("benchmarkRetrievalProfile", controller)

    def test_retrieval_profile_service_forbids_vector_only_default(self) -> None:
        service = (ROOT / "apps/api/src/retrieval/retrieval-profile.service.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn("vector_only_disabled", service)
        self.assertIn("metadata_filter_required", service)
        self.assertIn("identifier_match_enabled", service)
        self.assertIn("rerank_candidate_limit must be between 1 and 80", service)
        self.assertIn("max_context_tokens", service)
        self.assertIn("max_context_tokens must be positive", service)
        self.assertIn("final_context_limit must be positive", service)

    def test_candidate_union_contract_includes_metadata_identifier_vector_and_rerank(self) -> None:
        service = (ROOT / "apps/api/src/retrieval/retrieval-profile.service.ts").read_text(
            encoding="utf-8"
        )

        for token in (
            "metadata_exact",
            "identifier_exact",
            "pgvector",
            "findIdentifierMatches",
            "rerank_candidate_limit",
            "final_context_limit",
            "max_context_tokens",
        ):
            with self.subTest(token=token):
                self.assertIn(token, service)

    def test_identifier_match_covers_business_identifier_fields(self) -> None:
        identifier = (ROOT / "apps/api/src/retrieval/identifier-match.ts").read_text(
            encoding="utf-8"
        )
        for field in (
            "equipment_id",
            "alarm_code",
            "property_id",
            "room_number",
            "contract_id",
            "fund_id",
            "isin",
            "invoice_id",
        ):
            with self.subTest(field=field):
                self.assertIn(field, identifier)
        self.assertIn("normalizeIdentifier", identifier)


if __name__ == "__main__":
    unittest.main()
