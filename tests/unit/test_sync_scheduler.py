"""S2-1 (#0034) — auto-sync scheduler: parsing, due-ness, slot idempotency, tick behavior."""

from __future__ import annotations

import unittest
from datetime import datetime, time, timezone

from raku_rag.persistence.datasources import InMemoryDataSourceRepository
from raku_rag.persistence.secret_store import secret_store_from_settings
from raku_rag.core.config import Settings
from raku_rag.services.sync_scheduler import (
    AutoSyncScheduler,
    is_due,
    parse_sync_schedule,
    slot_key,
)

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


class TestParseSyncSchedule(unittest.TestCase):
    def test_japanese_and_english_formats(self) -> None:
        cases = {
            "毎日 03:00": ("daily", time(3, 0)),
            "毎日": ("daily", time(3, 0)),
            "daily 21:30": ("daily", time(21, 30)),
            "毎時": ("interval", 3600),
            "hourly": ("interval", 3600),
            "30分": ("interval", 1800),
            "2時間": ("interval", 7200),
            "15m": ("interval", 900),
            "2h": ("interval", 7200),
            "1d": ("interval", 86400),
            "weekly": ("interval", 7 * 86400),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                schedule = parse_sync_schedule(text)
                self.assertIsNotNone(schedule, text)
                self.assertEqual(schedule.kind, expected[0])
                if schedule.kind == "daily":
                    self.assertEqual(schedule.at, expected[1])
                else:
                    self.assertEqual(schedule.interval_seconds, expected[1])

    def test_unrecognized_and_empty_are_skipped(self) -> None:
        for text in ("なんとなく", "", None, "sometimes", "毎"):
            with self.subTest(text=text):
                self.assertIsNone(parse_sync_schedule(text))

    def test_minimum_interval_guardrail(self) -> None:
        schedule = parse_sync_schedule("1m")
        self.assertEqual(schedule.interval_seconds, 300)

    def test_describe(self) -> None:
        self.assertEqual(parse_sync_schedule("毎日 03:00").describe(), "毎日 03:00")
        self.assertEqual(parse_sync_schedule("weekly").describe(), "7日ごと")
        self.assertEqual(parse_sync_schedule("30分").describe(), "30分ごと")


class TestDueLogic(unittest.TestCase):
    def test_interval_due_when_never_synced(self) -> None:
        schedule = parse_sync_schedule("hourly")
        self.assertTrue(is_due(schedule, None, NOW))

    def test_interval_due_only_after_elapsed(self) -> None:
        schedule = parse_sync_schedule("hourly")
        self.assertFalse(is_due(schedule, "2026-07-02T11:30:00Z", NOW))
        self.assertTrue(is_due(schedule, "2026-07-02T10:59:00Z", NOW))

    def test_daily_fires_once_after_threshold(self) -> None:
        schedule = parse_sync_schedule("毎日 03:00")
        # Last synced before today's 03:00 -> due at 12:00.
        self.assertTrue(is_due(schedule, "2026-07-01T03:05:00Z", NOW))
        # Already synced after today's 03:00 -> not due again today.
        self.assertFalse(is_due(schedule, "2026-07-02T03:05:00Z", NOW))

    def test_daily_before_todays_threshold_uses_yesterday(self) -> None:
        schedule = parse_sync_schedule("毎日 23:00")
        # At 12:00 the most recent threshold is YESTERDAY 23:00.
        self.assertFalse(is_due(schedule, "2026-07-01T23:30:00Z", NOW))
        self.assertTrue(is_due(schedule, "2026-07-01T22:00:00Z", NOW))

    def test_slot_key_is_stable_within_a_slot(self) -> None:
        schedule = parse_sync_schedule("hourly")
        a = slot_key(schedule, NOW)
        b = slot_key(schedule, NOW.replace(minute=45))
        self.assertEqual(a, b)
        c = slot_key(schedule, NOW.replace(hour=13))
        self.assertNotEqual(a, c)
        daily = parse_sync_schedule("毎日 03:00")
        self.assertEqual(slot_key(daily, NOW), "20260702T0300")


class TestSchedulerTick(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryDataSourceRepository(
            secret_store_from_settings(Settings())
        )
        self.fired: list[tuple[str, str, str]] = []
        self.pruned: list[tuple[str, str]] = []
        self.scheduler = AutoSyncScheduler(
            list_scheduled=self.repo.list_scheduled,
            get_source=self.repo.get,
            trigger=lambda t, s, k: self.fired.append((t, s, k)),
            prune=lambda t, s: self.pruned.append((t, s)),
            now_fn=lambda: NOW,
        )

    def test_fires_due_sources_with_slot_scoped_idempotency_key(self) -> None:
        self.repo.upsert("tenant_a", "src_docs", {"type": "url", "sync_schedule": "hourly"})
        fired = self.scheduler.tick()
        self.assertEqual(len(fired), 1)
        tenant, source, key = fired[0]
        self.assertEqual((tenant, source), ("tenant_a", "src_docs"))
        self.assertTrue(key.startswith("auto-sync:src_docs:i3600-"))
        # Same tick slot -> same key (dedupe anchor for the runs store).
        fired_again = self.scheduler.tick()
        self.assertEqual(fired_again[0][2], key)

    def test_unscheduled_and_invalid_sources_are_skipped(self) -> None:
        self.repo.upsert("tenant_a", "src_plain", {"type": "url"})
        self.repo.upsert("tenant_a", "src_typo", {"type": "url", "sync_schedule": "たまに"})
        self.assertEqual(self.scheduler.tick(), [])

    def test_missing_source_is_pruned(self) -> None:
        entries = [{"tenant_id": "tenant_a", "source_id": "gone", "sync_schedule": "hourly"}]
        scheduler = AutoSyncScheduler(
            list_scheduled=lambda: entries,
            get_source=lambda t, s: None,
            trigger=lambda t, s, k: self.fired.append((t, s, k)),
            prune=lambda t, s: self.pruned.append((t, s)),
            now_fn=lambda: NOW,
        )
        scheduler.tick()
        self.assertEqual(self.pruned, [("tenant_a", "gone")])
        self.assertEqual(self.fired, [])

    def test_one_broken_source_does_not_stop_the_tick(self) -> None:
        self.repo.upsert("tenant_a", "src_ok", {"type": "url", "sync_schedule": "hourly"})
        entries = self.repo.list_scheduled() + [
            {"tenant_id": "tenant_b", "source_id": "src_boom", "sync_schedule": "hourly"}
        ]

        def get_source(tenant_id: str, source_id: str):
            if source_id == "src_boom":
                raise RuntimeError("db down")
            return self.repo.get(tenant_id, source_id)

        scheduler = AutoSyncScheduler(
            list_scheduled=lambda: entries,
            get_source=get_source,
            trigger=lambda t, s, k: self.fired.append((t, s, k)),
            now_fn=lambda: NOW,
        )
        fired = scheduler.tick()
        self.assertEqual([(t, s) for t, s, _ in fired], [("tenant_a", "src_ok")])


if __name__ == "__main__":
    unittest.main()
