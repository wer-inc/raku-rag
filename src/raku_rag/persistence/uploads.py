"""0045 — S3 upload provenance records.

The web presign route registers every presigned S3 object here BEFORE the browser receives the PUT
URL; ingest then resolves ``upload_id`` -> (bucket, key) from the record instead of trusting a raw
caller-supplied ``s3://`` ref. Records are one-time-use (``consumed_at``) and expire. The Postgres
adapter targets ``upload_records`` (0020, RLS-forced) and follows the datasource/chatbot precedent:
every query runs after ``_use_tenant`` so RLS enforces isolation even if a WHERE clause is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


@dataclass
class UploadRecord:
    tenant_id: str
    upload_id: str
    user_id: str = ""
    bucket: str = ""
    object_key: str = ""
    content_type: str = ""
    content_length: int | None = None
    filename: str = ""
    created_at: str = ""
    expires_at: str = ""
    consumed_at: str = ""
    consumed_by_run: str = ""

    def is_expired(self, now: datetime | None = None) -> bool:
        if not self.expires_at:
            return False
        moment = (now or _now()).isoformat()
        return self.expires_at.replace("Z", "+00:00") < moment

    def public(self) -> dict:
        return {
            "upload_id": self.upload_id,
            "bucket": self.bucket,
            "object_key": self.object_key,
            "content_type": self.content_type,
            "content_length": self.content_length,
            "filename": self.filename,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at or None,
        }


def build_upload_record(
    *,
    tenant_id: str,
    upload_id: str,
    user_id: str,
    bucket: str,
    object_key: str,
    content_type: str = "",
    content_length: int | None = None,
    filename: str = "",
    ttl_seconds: int = 24 * 60 * 60,
) -> UploadRecord:
    now = _now()
    return UploadRecord(
        tenant_id=tenant_id,
        upload_id=upload_id,
        user_id=user_id,
        bucket=bucket,
        object_key=object_key,
        content_type=content_type,
        content_length=content_length,
        filename=filename,
        created_at=_iso(now),
        expires_at=_iso(now + timedelta(seconds=max(60, ttl_seconds))),
    )


@dataclass
class InMemoryUploadRecordRepository:
    """Tenant-keyed provenance records (UploadRecordRepository contract)."""

    _items: dict[tuple[str, str], UploadRecord] = field(default_factory=dict)

    def save(self, record: UploadRecord) -> None:
        self._items[(record.tenant_id, record.upload_id)] = record

    def get(self, tenant_id: str, upload_id: str) -> UploadRecord | None:
        return self._items.get((tenant_id, upload_id))

    def mark_consumed(self, tenant_id: str, upload_id: str, run_id: str) -> bool:
        record = self._items.get((tenant_id, upload_id))
        if record is None or record.consumed_at:
            return False
        record.consumed_at = _iso(_now())
        record.consumed_by_run = run_id
        return True


class PostgresUploadRecordRepository:
    """upload_records (0020) — typed columns, RLS-forced."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def save(self, record: UploadRecord) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, record.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (record.tenant_id,),
            )
            cur.execute(
                "INSERT INTO upload_records "
                "(tenant_id, upload_id, user_id, bucket, object_key, content_type, "
                " content_length, filename, created_at, expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s, "
                " COALESCE(%s::timestamptz, now()), %s::timestamptz) "
                "ON CONFLICT (tenant_id, upload_id) DO NOTHING",
                (
                    record.tenant_id,
                    record.upload_id,
                    record.user_id,
                    record.bucket,
                    record.object_key,
                    record.content_type,
                    record.content_length,
                    record.filename,
                    record.created_at or None,
                    record.expires_at or None,
                ),
            )

    def get(self, tenant_id: str, upload_id: str) -> UploadRecord | None:
        from raku_rag.persistence.postgres import _iso as _pg_iso
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, upload_id, user_id, bucket, object_key, content_type, "
                "content_length, filename, created_at, expires_at, consumed_at, consumed_by_run "
                "FROM upload_records WHERE tenant_id = %s AND upload_id = %s",
                (tenant_id, upload_id),
            )
            row = cur.fetchone()
        if not row:
            return None
        return UploadRecord(
            tenant_id=row[0],
            upload_id=row[1],
            user_id=row[2] or "",
            bucket=row[3],
            object_key=row[4],
            content_type=row[5] or "",
            content_length=row[6],
            filename=row[7] or "",
            created_at=_pg_iso(row[8]) or "",
            expires_at=_pg_iso(row[9]) or "",
            consumed_at=_pg_iso(row[10]) or "",
            consumed_by_run=row[11] or "",
        )

    def mark_consumed(self, tenant_id: str, upload_id: str, run_id: str) -> bool:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            # Atomic one-time consumption: the WHERE clause loses the race for a second consumer.
            cur.execute(
                "UPDATE upload_records SET consumed_at = now(), consumed_by_run = %s "
                "WHERE tenant_id = %s AND upload_id = %s AND consumed_at IS NULL",
                (run_id, tenant_id, upload_id),
            )
            return cur.rowcount == 1
