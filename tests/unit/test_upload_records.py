"""0045 — upload provenance record lifecycle (register / resolve / one-time consume / expiry)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raku_rag.persistence.uploads import (
    InMemoryUploadRecordRepository,
    build_upload_record,
)


def _record(**overrides):
    values = dict(
        tenant_id="tenant_a",
        upload_id="up_1",
        user_id="alice",
        bucket="docs-bucket",
        object_key="tenants/tenant_a/uploads/2026-07-02/up_1.pdf",
        content_type="application/pdf",
        content_length=1234,
        filename="manual.pdf",
    )
    values.update(overrides)
    return build_upload_record(**values)


class UploadRecordTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryUploadRecordRepository()

    def test_register_and_resolve_is_tenant_scoped(self) -> None:
        self.repo.save(_record())
        found = self.repo.get("tenant_a", "up_1")
        self.assertIsNotNone(found)
        self.assertEqual(found.bucket, "docs-bucket")
        self.assertTrue(found.expires_at)
        self.assertIsNone(self.repo.get("tenant_b", "up_1"))

    def test_consumption_is_one_time(self) -> None:
        self.repo.save(_record())
        self.assertTrue(self.repo.mark_consumed("tenant_a", "up_1", "ing_1"))
        record = self.repo.get("tenant_a", "up_1")
        self.assertTrue(record.consumed_at)
        self.assertEqual(record.consumed_by_run, "ing_1")
        self.assertFalse(self.repo.mark_consumed("tenant_a", "up_1", "ing_2"))
        self.assertEqual(self.repo.get("tenant_a", "up_1").consumed_by_run, "ing_1")

    def test_cross_tenant_consumption_is_refused(self) -> None:
        self.repo.save(_record())
        self.assertFalse(self.repo.mark_consumed("tenant_b", "up_1", "ing_x"))
        self.assertFalse(self.repo.get("tenant_a", "up_1").consumed_at)

    def test_expiry(self) -> None:
        record = _record(ttl_seconds=60)
        self.assertFalse(record.is_expired())
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        self.assertTrue(record.is_expired(now=future))

    def test_ttl_floor(self) -> None:
        record = _record(ttl_seconds=-5)
        # Nonsense TTLs still leave a usable (>= 60s) window instead of a born-dead record.
        self.assertFalse(record.is_expired())


if __name__ == "__main__":
    unittest.main()
