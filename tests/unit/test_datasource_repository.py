from __future__ import annotations

import unittest

from raku_rag.persistence.datasources import (
    InMemoryDataSourceRepository,
    materialize_datasource_credentials,
)
from raku_rag.persistence.secret_store import InMemorySecretStore


class TestDataSourceRepository(unittest.TestCase):
    def test_upsert_moves_credentials_out_of_public_config(self) -> None:
        secrets = InMemorySecretStore()
        repo = InMemoryDataSourceRepository(secrets)

        saved = repo.upsert(
            "tenant_a",
            "confluence_main",
            {
                "collection_id": "manuals",
                "type": "confluence",
                "config": {
                    "source_type": "confluence",
                    "site_url": "https://example.atlassian.net/wiki",
                    "space_key": "MFG",
                    "api_token": "secret-token",
                },
                "credentials": {"password": "secret-password"},
            },
        )

        self.assertNotIn("api_token", saved["config"])
        self.assertNotIn("password", saved["config"])
        self.assertEqual(saved["config"]["credential_status"], "configured")
        materialized = materialize_datasource_credentials(saved, secrets)
        self.assertEqual(materialized["config"]["api_token"], "secret-token")
        self.assertEqual(materialized["config"]["password"], "secret-password")


if __name__ == "__main__":
    unittest.main()
