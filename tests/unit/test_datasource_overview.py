from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
_SERVER = ROOT / "apps/answer-service/server.py"


def _load_server():
    spec = importlib.util.spec_from_file_location("answer_service_server_overview", _SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Runs:
    def source_sync_state(self, tenant_id: str, source_id: str):
        return None


class DataSourceOverviewProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = _load_server()

    def test_credential_status_is_projected_from_public_config(self) -> None:
        rows = self.server._datasource_overview_rows(
            [
                {
                    "source_id": "box-main",
                    "tenant_id": "tenant_a",
                    "collection_id": "manuals",
                    "type": "box",
                    "status": "active",
                    "config": {
                        "display_name": "Box Manuals",
                        "source_type": "box",
                        "credential_status": "configured",
                    },
                }
            ],
            [],
            _Runs(),
            "tenant_a",
        )

        self.assertEqual(rows[0]["credential_status"], "configured")
        self.assertNotIn("config", rows[0])

    def test_credential_ref_is_not_returned_but_marks_configured(self) -> None:
        rows = self.server._datasource_overview_rows(
            [
                {
                    "source_id": "s3-main",
                    "tenant_id": "tenant_a",
                    "collection_id": "manuals",
                    "type": "object_storage",
                    "status": "active",
                    "config": {"source_type": "s3", "credential_ref": "datasources/s3-main"},
                }
            ],
            [],
            _Runs(),
            "tenant_a",
        )

        self.assertEqual(rows[0]["credential_status"], "configured")
        self.assertNotIn("credential_ref", rows[0])


if __name__ == "__main__":
    unittest.main()
