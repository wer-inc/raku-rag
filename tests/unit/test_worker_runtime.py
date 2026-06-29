from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from workers.ingest import worker as worker_module


class TestWorkerRuntime(unittest.TestCase):
    def test_postgres_worker_passes_env_settings_to_production_system(self) -> None:
        captured: dict[str, object] = {}

        class FakeProductionSystem:
            def __init__(self, dsn: str, settings=None, *, reset: bool = False) -> None:
                captured["dsn"] = dsn
                captured["settings"] = settings
                captured["system"] = self
                self._conn = object()
                self.ingestion = object()
                self.ingestion_executor = object()

        class FakeRunStore:
            def __init__(self, conn: object) -> None:
                self.conn = conn

        class FakeDataSourceRepository:
            def __init__(self, conn: object, secret_store: object) -> None:
                self.conn = conn
                self.secret_store = secret_store

        env = {
            "RAKU_WORKER_BACKEND": "postgres",
            "POSTGRES_URL": "postgresql://raku@db/raku",
            "RAKU_CROP_STORAGE_URI": "s3://bucket/visual-crops",
            "RAKU_VISUAL_EVIDENCE_PROMOTION": "true",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch("raku_rag.production.ProductionSystem", FakeProductionSystem),
            patch("raku_rag.persistence.postgres.PostgresIngestionRunStore", FakeRunStore),
            patch.object(worker_module, "PostgresDataSourceRepository", FakeDataSourceRepository),
            patch.object(worker_module, "SourceSyncService", lambda **kwargs: object()),
        ):
            built = worker_module.build_worker_from_env()

        settings = captured["settings"]
        self.assertEqual(captured["dsn"], env["POSTGRES_URL"])
        self.assertEqual(settings.crop_storage_uri, "s3://bucket/visual-crops")
        self.assertTrue(settings.visual_evidence_promotion)
        self.assertIs(built.executor, captured["system"].ingestion_executor)


if __name__ == "__main__":
    unittest.main()
