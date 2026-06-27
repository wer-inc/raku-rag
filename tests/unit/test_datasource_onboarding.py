from __future__ import annotations

import unittest
from unittest.mock import patch

from raku_rag.persistence.datasources import InMemoryDataSourceRepository
from raku_rag.persistence.secret_store import InMemorySecretStore
from raku_rag.services.datasource_sync import SyncDocument
from raku_rag.services.source_sync import SourceSyncService
from raku_rag.workers.ingestion import IngestionRunStore


class TestDatasourceOnboardingPreview(unittest.TestCase):
    def test_preview_suggests_mapping_normalizes_rows_and_flags_needs_review(self) -> None:
        secrets = InMemorySecretStore()
        repo = InMemoryDataSourceRepository(secrets)
        repo.upsert(
            "tenant_a",
            "csv-trouble",
            {
                "collection_id": "manuals",
                "type": "object_storage",
                "config": {
                    "source_type": "s3",
                    "bucket": "pilot",
                    "mapping_profile": {
                        "field_mapping": {"設備番号": "equipment_id"},
                        "defaults": {"document_kind": "トラブル報告"},
                        "required_fields": ["equipment_id", "alarm_code"],
                    },
                },
            },
        )
        service = SourceSyncService(
            system=object(),
            runs=IngestionRunStore(),
            datasource_repo=repo,
            secret_store=secrets,
        )
        csv_bytes = (
            "設備番号,アラーム,不具合分類,承認状態,有効日\n"
            "M-100,E152,crack,承認済み,2026/06/01\n"
            ",E153,leak,謎,not-a-date\n"
        ).encode("utf-8")

        with patch(
            "raku_rag.services.source_sync.build_sync_documents",
            return_value=[
                SyncDocument(
                    document_id="csv-trouble-sample",
                    document_ref="s3://pilot/trouble.csv",
                    raw=csv_bytes,
                    content_type="text/csv",
                )
            ],
        ):
            preview = service.preview_source(
                tenant_id="tenant_a",
                source_id="csv-trouble",
                body={"sample_rows": 2},
            )

        self.assertEqual(preview["source_id"], "csv-trouble")
        self.assertEqual(preview["profile_type"], "manufacturing")
        self.assertEqual(preview["suggested_mapping"]["設備番号"], "equipment_id")
        self.assertEqual(preview["suggested_mapping"]["アラーム"], "alarm_code")
        self.assertEqual(preview["suggested_mapping"]["不具合分類"], "defect_type")
        self.assertEqual(preview["defaults"], {"document_kind": "trouble_report"})
        first = preview["sample_rows"][0]
        self.assertEqual(first["normalized"]["equipment_id"], "M-100")
        self.assertEqual(first["normalized"]["approval_status"], "approved")
        self.assertEqual(first["normalized"]["effective_date"], "2026-06-01")
        self.assertEqual(first["validation"]["status"], "valid")
        second = preview["sample_rows"][1]
        self.assertEqual(second["validation"]["status"], "needs_review")
        self.assertIn("missing required field: equipment_id", second["validation"]["errors"])
        self.assertIn("unknown approval_status", " ".join(second["validation"]["warnings"]))
        self.assertEqual(preview["validation"]["valid_count"], 1)
        self.assertEqual(preview["validation"]["needs_review_count"], 1)

    def test_text_document_preview_does_not_require_table_mapping(self) -> None:
        secrets = InMemorySecretStore()
        repo = InMemoryDataSourceRepository(secrets)
        repo.upsert(
            "tenant_a",
            "page",
            {
                "collection_id": "manuals",
                "type": "object_storage",
                "config": {"source_type": "url", "target_url": "https://example.com/manual"},
            },
        )
        service = SourceSyncService(
            system=object(),
            runs=IngestionRunStore(),
            datasource_repo=repo,
            secret_store=secrets,
        )
        with patch(
            "raku_rag.services.source_sync.build_sync_documents",
            return_value=[
                SyncDocument(
                    document_id="page-1",
                    document_ref="https://example.com/manual",
                    raw=b"<h1>Manual</h1><p>Inspect the pump before restart.</p>",
                    content_type="text/html",
                )
            ],
        ):
            preview = service.preview_source(tenant_id="tenant_a", source_id="page")

        self.assertEqual(preview["detected_columns"], [])
        self.assertEqual(preview["sample_rows"], [])
        self.assertEqual(preview["profile_type"], "manual")
        self.assertEqual(preview["documents"][0]["kind"], "text")
        self.assertIn("Inspect the pump", preview["documents"][0]["text_preview"])

    def test_faq_csv_preview_uses_content_profile_without_code_changes(self) -> None:
        secrets = InMemorySecretStore()
        repo = InMemoryDataSourceRepository(secrets)
        repo.upsert(
            "tenant_a",
            "faq",
            {
                "collection_id": "manuals",
                "type": "object_storage",
                "config": {
                    "source_type": "s3",
                    "bucket": "pilot",
                    "mapping_profile": {"profile_type": "auto"},
                },
            },
        )
        service = SourceSyncService(
            system=object(),
            runs=IngestionRunStore(),
            datasource_repo=repo,
            secret_store=secrets,
        )
        csv_bytes = (
            "質問,回答,カテゴリ,公開日\n"
            "異音が出る場合は?,軸受と潤滑状態を確認してください,保全,2026/06/10\n"
        ).encode("utf-8")

        with patch(
            "raku_rag.services.source_sync.build_sync_documents",
            return_value=[
                SyncDocument(
                    document_id="faq-sample",
                    document_ref="s3://pilot/faq.csv",
                    raw=csv_bytes,
                    content_type="text/csv",
                )
            ],
        ):
            preview = service.preview_source(tenant_id="tenant_a", source_id="faq")

        self.assertEqual(preview["profile_type"], "faq")
        self.assertEqual(preview["suggested_mapping"]["質問"], "question")
        self.assertEqual(preview["suggested_mapping"]["回答"], "answer")
        self.assertEqual(preview["suggested_mapping"]["公開日"], "published_at")
        self.assertIn("question", preview["canonical_fields"])
        self.assertIn("answer", preview["required_fields"])
        self.assertEqual(preview["sample_rows"][0]["normalized"]["question"], "異音が出る場合は?")
        self.assertEqual(preview["sample_rows"][0]["normalized"]["published_at"], "2026-06-10")
        self.assertEqual(preview["validation"]["valid_count"], 1)

    def test_manual_csv_profile_can_be_selected_from_mapping_profile(self) -> None:
        secrets = InMemorySecretStore()
        repo = InMemoryDataSourceRepository(secrets)
        repo.upsert(
            "tenant_a",
            "manual-table",
            {
                "collection_id": "manuals",
                "type": "object_storage",
                "config": {
                    "source_type": "s3",
                    "bucket": "pilot",
                    "mapping_profile": {
                        "profile_type": "manual",
                        "required_fields": ["document_title", "body"],
                    },
                },
            },
        )
        service = SourceSyncService(
            system=object(),
            runs=IngestionRunStore(),
            datasource_repo=repo,
            secret_store=secrets,
        )
        csv_bytes = "文書名,章,本文\nPW-E2 手順書,起動前点検,圧力計を確認してください\n".encode(
            "utf-8"
        )

        with patch(
            "raku_rag.services.source_sync.build_sync_documents",
            return_value=[
                SyncDocument(
                    document_id="manual-table-sample",
                    document_ref="s3://pilot/manual.csv",
                    raw=csv_bytes,
                    content_type="text/csv",
                )
            ],
        ):
            preview = service.preview_source(tenant_id="tenant_a", source_id="manual-table")

        self.assertEqual(preview["profile_type"], "manual")
        self.assertEqual(preview["suggested_mapping"]["文書名"], "document_title")
        self.assertEqual(preview["suggested_mapping"]["章"], "section")
        self.assertEqual(preview["suggested_mapping"]["本文"], "body")
        self.assertEqual(preview["required_fields"], ["document_title", "body"])
        self.assertEqual(preview["sample_rows"][0]["validation"]["status"], "valid")


if __name__ == "__main__":
    unittest.main()
