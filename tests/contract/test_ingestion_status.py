from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class IngestionStatusContractTest(unittest.TestCase):
    def test_admin_ingestion_status_contract_is_published(self) -> None:
        openapi = (ROOT / "apps/api/src/openapi/openapi.controller.ts").read_text()
        controller = (ROOT / "apps/api/src/admin/jobs.controller.ts").read_text()

        for route in (
            "/admin/jobs",
            "/admin/sources/{source_id}/sync-status",
            "/admin/ingestion-runs/{ingestion_run_id}",
            "/admin/ingestion-runs/{ingestion_run_id}/retry",
            "/admin/documents/{document_id}/processing-status",
            "/admin/documents/{document_id}",
            "/admin/collections/{collection_id}/reindex",
        ):
            with self.subTest(route=route):
                self.assertIn(route, openapi)

        for schema in (
            "SourceSyncStatus",
            "IngestionRunStatus",
            "DocumentProcessingStatus",
            "DeleteDocumentResponse",
            "ReindexResponse",
            "AdminJobSummary",
        ):
            with self.subTest(schema=schema):
                self.assertIn(f"#/components/schemas/{schema}", openapi)

        self.assertIn('@Get("jobs")', controller)
        self.assertIn('@Get("sources/:source_id/sync-status")', controller)
        self.assertIn('@Get("ingestion-runs/:ingestion_run_id")', controller)
        self.assertIn('@Post("ingestion-runs/:ingestion_run_id/retry")', controller)
        self.assertIn('@Post("collections/:collection_id/reindex")', controller)
        self.assertIn('@Get("documents/:document_id/processing-status")', controller)
        self.assertIn('@Delete("documents/:document_id")', controller)
        self.assertIn("x-raku-tenant-id", controller)

        # 0085: the processing-status READ is role-gated server-side (defense-in-depth). ops_owner MUST
        # be in the set — it is the documents manager and owns the /documents screen (see nav-rbac).
        self.assertIn("assertAnyRoleAllowed", controller)
        self.assertIn(
            '["ops_owner", "tenant_admin", "platform_admin", "admin", "owner"]',
            controller,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
