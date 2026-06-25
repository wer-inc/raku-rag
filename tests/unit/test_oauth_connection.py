from __future__ import annotations

import unittest

from raku_rag.persistence.oauth_connection import (
    InMemoryOAuthConnectionStore,
    OAuthConnection,
    build_connection,
    new_connection_id,
    secret_ref_for,
)


class BuildConnectionTest(unittest.TestCase):
    def test_generates_id_and_derived_secret_ref(self) -> None:
        conn = build_connection(tenant_id="tenant_a", source_id="src-1", scope="drive.readonly")
        self.assertTrue(conn.connection_id)
        self.assertEqual(conn.refresh_token_secret_ref, f"gdrive/{conn.connection_id}")
        self.assertEqual(conn.provider, "google_drive")
        self.assertEqual(conn.status, "connected")

    def test_ids_are_unique(self) -> None:
        self.assertNotEqual(new_connection_id(), new_connection_id())

    def test_secret_ref_excludes_tenant(self) -> None:
        # tenant is applied by the SecretStore; the ref must not embed it (no double-encoding).
        ref = secret_ref_for("abc123")
        self.assertEqual(ref, "gdrive/abc123")
        self.assertNotIn("tenant", ref)


class InMemoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryOAuthConnectionStore()

    def test_upsert_and_get(self) -> None:
        conn = build_connection(tenant_id="tenant_a", source_id="src-1")
        self.store.upsert(conn)
        got = self.store.get("tenant_a", conn.connection_id)
        self.assertIsNotNone(got)
        self.assertEqual(got.source_id, "src-1")

    def test_get_by_source(self) -> None:
        conn = build_connection(tenant_id="tenant_a", source_id="src-1")
        self.store.upsert(conn)
        got = self.store.get_by_source("tenant_a", "src-1")
        self.assertEqual(got.connection_id, conn.connection_id)
        self.assertIsNone(self.store.get_by_source("tenant_a", "missing"))

    def test_tenant_isolation(self) -> None:
        conn = build_connection(tenant_id="tenant_a", source_id="src-1")
        self.store.upsert(conn)
        self.assertIsNone(self.store.get("tenant_b", conn.connection_id))
        self.assertIsNone(self.store.get_by_source("tenant_b", "src-1"))

    def test_delete(self) -> None:
        conn = build_connection(tenant_id="tenant_a", source_id="src-1")
        self.store.upsert(conn)
        self.assertTrue(self.store.delete("tenant_a", conn.connection_id))
        self.assertFalse(self.store.delete("tenant_a", conn.connection_id))
        self.assertIsNone(self.store.get("tenant_a", conn.connection_id))

    def test_upsert_stamps_updated_at_and_returns_stored(self) -> None:
        conn = OAuthConnection(
            tenant_id="tenant_a",
            connection_id="c1",
            source_id="src-1",
            provider="google_drive",
            refresh_token_secret_ref="gdrive/c1",
            updated_at="2000-01-01T00:00:00Z",
        )
        stored = self.store.upsert(conn)
        self.assertNotEqual(stored.updated_at, "2000-01-01T00:00:00Z")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
