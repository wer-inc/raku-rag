"""S2-1 (#0034) — auto-sync scheduler: the missing execution half of `sync_schedule`.

Datasources have stored a `sync_schedule` string since 0001, but nothing ever ran it — "自動同期"
was a saved setting with no engine. This module parses the human-entered schedule formats the UI
placeholder suggests (「毎日 03:00」等), decides due-ness against `last_synced_at`, and fires the
EXISTING manual-sync path with a slot-scoped idempotency key so a restart or overlapping tick can
never double-enqueue the same slot.

Threading model (server wiring): the scheduler thread owns a PRIVATE DB connection and talks to
the sync path over the service's own internal HTTP route — it never shares the request thread's
psycopg connection or in-memory stores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Callable

# --- schedule parsing ---------------------------------------------------------------------------

_INTERVAL_PATTERNS: tuple[tuple[re.Pattern, int], ...] = (
    (re.compile(r"^(\d+)\s*(?:m|min|分)(?:ごと|毎|おき)?$", re.IGNORECASE), 60),
    (re.compile(r"^(\d+)\s*(?:h|hour|時間)(?:ごと|毎|おき)?$", re.IGNORECASE), 3600),
    (re.compile(r"^(\d+)\s*(?:d|day|日)(?:ごと|毎|おき)?$", re.IGNORECASE), 86400),
)

_DAILY_AT = re.compile(r"^(?:毎日|daily)\s*(?:([01]?\d|2[0-3])[:時]([0-5]\d)?\s*(?:分)?)?$",
                       re.IGNORECASE)

_MIN_INTERVAL_SECONDS = 300  # guardrail: never hammer a source more often than every 5 minutes


@dataclass(frozen=True)
class SyncSchedule:
    kind: str  # "interval" | "daily"
    interval_seconds: int = 0
    at: time | None = None  # daily fire time (UTC-naive wall time applied in UTC)

    def describe(self) -> str:
        if self.kind == "daily":
            return f"毎日 {self.at.strftime('%H:%M')}" if self.at else "毎日"
        if self.interval_seconds % 86400 == 0:
            return f"{self.interval_seconds // 86400}日ごと"
        hours, remainder = divmod(self.interval_seconds, 3600)
        minutes = remainder // 60
        if hours and not minutes:
            return f"{hours}時間ごと"
        if not hours:
            return f"{minutes}分ごと"
        return f"{hours}時間{minutes}分ごと"


def parse_sync_schedule(value: str | None) -> SyncSchedule | None:
    """Parse the free-text schedule field; None = not scheduled / unrecognized (skipped)."""
    text = (value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"hourly", "毎時", "毎時間", "1時間ごと"}:
        return SyncSchedule(kind="interval", interval_seconds=3600)
    if lowered in {"weekly", "毎週"}:
        return SyncSchedule(kind="interval", interval_seconds=7 * 86400)
    daily = _DAILY_AT.match(text)
    if daily:
        hour = daily.group(1)
        minute = daily.group(2)
        at = time(int(hour), int(minute or 0)) if hour is not None else time(3, 0)
        return SyncSchedule(kind="daily", at=at)
    for pattern, unit_seconds in _INTERVAL_PATTERNS:
        match = pattern.match(text)
        if match:
            seconds = int(match.group(1)) * unit_seconds
            if seconds <= 0:
                return None
            return SyncSchedule(
                kind="interval", interval_seconds=max(seconds, _MIN_INTERVAL_SECONDS)
            )
    return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _daily_threshold(schedule: SyncSchedule, now: datetime) -> datetime:
    """The most recent scheduled fire time at or before `now` (UTC wall clock)."""
    at = schedule.at or time(3, 0)
    candidate = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if candidate > now:
        candidate -= timedelta(days=1)
    return candidate


def is_due(schedule: SyncSchedule, last_synced_at: str | None, now: datetime) -> bool:
    last = _parse_iso(last_synced_at)
    if schedule.kind == "daily":
        threshold = _daily_threshold(schedule, now)
        return last is None or last < threshold
    if last is None:
        return True
    return (now - last).total_seconds() >= schedule.interval_seconds


def slot_key(schedule: SyncSchedule, now: datetime) -> str:
    """Deterministic id of the CURRENT schedule slot — the dedupe anchor for idempotency keys."""
    if schedule.kind == "daily":
        return _daily_threshold(schedule, now).strftime("%Y%m%dT%H%M")
    bucket = int(now.timestamp()) // max(schedule.interval_seconds, 1)
    return f"i{schedule.interval_seconds}-{bucket}"


# --- scheduler ----------------------------------------------------------------------------------


class AutoSyncScheduler:
    """One tick = scan scheduled sources, fire the due ones through the injected trigger.

    All collaborators are injected callables so ticks are fully deterministic in tests:
    - list_scheduled(): [{tenant_id, source_id, sync_schedule}] (registry / in-memory scan)
    - get_source(tenant_id, source_id) -> dict | None  (RLS-checked re-resolution)
    - trigger(tenant_id, source_id, idempotency_key)   (existing manual-sync path)
    - prune(tenant_id, source_id)                      (drop stale registry rows)
    """

    def __init__(
        self,
        *,
        list_scheduled: Callable[[], list[dict]],
        get_source: Callable[[str, str], dict | None],
        trigger: Callable[[str, str, str], None],
        prune: Callable[[str, str], None] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        log: Callable[..., None] | None = None,
    ) -> None:
        self._list_scheduled = list_scheduled
        self._get_source = get_source
        self._trigger = trigger
        self._prune = prune
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._log = log or (lambda *a, **k: None)

    def tick(self) -> list[tuple[str, str, str]]:
        fired: list[tuple[str, str, str]] = []
        now = self._now_fn()
        try:
            entries = self._list_scheduled()
        except Exception as exc:  # noqa: BLE001 — a broken registry must not kill the loop
            self._log("auto_sync.registry_error", error=str(exc))
            return fired
        for entry in entries:
            tenant_id = str(entry.get("tenant_id") or "")
            source_id = str(entry.get("source_id") or "")
            if not tenant_id or not source_id:
                continue
            try:
                source = self._get_source(tenant_id, source_id)
                if source is None:
                    # Datasource deleted / no longer visible: self-heal the registry.
                    if self._prune:
                        self._prune(tenant_id, source_id)
                    continue
                schedule = parse_sync_schedule(
                    str(source.get("sync_schedule") or entry.get("sync_schedule") or "")
                )
                if schedule is None:
                    continue
                if not is_due(schedule, source.get("last_synced_at"), now):
                    continue
                key = f"auto-sync:{source_id}:{slot_key(schedule, now)}"
                self._trigger(tenant_id, source_id, key)
                fired.append((tenant_id, source_id, key))
                self._log("auto_sync.fired", tenant=tenant_id, source=source_id, key=key)
            except Exception as exc:  # noqa: BLE001 — isolate per-source failures
                self._log(
                    "auto_sync.source_error", tenant=tenant_id, source=source_id, error=str(exc)
                )
        return fired
