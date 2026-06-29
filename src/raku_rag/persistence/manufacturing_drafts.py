"""PostgresDraftStore — durable DraftArtifact storage (issue 0012).

Backs the ``manufacturing_draft_artifacts`` table (migration 0006) so the AI-draft review queue
survives an answer-service restart and is shared across Fargate tasks, instead of the process-local
``InMemoryDraftStore``. This is the production counterpart wired by
``production.build_manufacturing_system_for_base``.

Tenant isolation: every statement runs ``_use_tenant`` first, so RLS scopes reads/writes to the
caller's tenant (matching the sibling Postgres stores). The connection is autocommit.

Column vs payload split: the queryable / CHECK-constrained fields (artifact_type / status /
created_by / reviewer_id / reviewer_group / source_document_ids / source_citations / audit_log_ref)
map to real columns; the remaining DraftArtifact fields — the generated ``content`` plus
collection_id / template_id / reviewer_role / assigned_at / reviewed_at / review_comment /
approval_decision / review_status — ride in the ``payload`` jsonb so nothing is lost on round-trip
WITHOUT a schema migration. (Promoting those to indexed columns is a possible follow-up.)
"""

from __future__ import annotations

import json
import uuid

from raku_rag.manufacturing.domain.draft import (
    CreatedBy,
    DraftArtifact,
    DraftStatus,
    DraftType,
)
from raku_rag.persistence.postgres import _use_tenant

_TABLE = "manufacturing_draft_artifacts"

# DraftArtifact fields that have no dedicated column and are carried inside the payload jsonb.
_PAYLOAD_FIELDS = (
    "collection_id",
    "template_id",
    "reviewer_role",
    "assigned_at",
    "reviewed_at",
    "review_comment",
    "approval_decision",
    "review_status",
)

_SELECT = (
    "SELECT artifact_id, tenant_id, artifact_type, status, created_by, reviewer_id, reviewer_group, "
    "source_document_ids, source_citations, payload, audit_log_ref, created_at "
    f"FROM {_TABLE}"
)


class PostgresDraftStore:
    """Durable DraftStore over ``manufacturing_draft_artifacts`` (RLS-scoped, autocommit)."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def next_id(self) -> str:
        # Globally unique so concurrent answer-service instances never collide (the in-memory
        # itertools counter would mint the same art_1 in two processes).
        return f"art_{uuid.uuid4().hex}"

    def add(self, artifact: DraftArtifact) -> None:
        _use_tenant(self._conn, artifact.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {_TABLE} "
                "(artifact_id, tenant_id, artifact_type, status, created_by, reviewer_id, "
                "reviewer_group, source_document_ids, source_citations, payload, audit_log_ref, "
                "created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,COALESCE(%s::timestamptz, now()),now())",
                _insert_params(artifact),
            )

    def save(self, artifact: DraftArtifact) -> None:
        # Upsert so save() honors the DraftStore contract (InMemoryDraftStore.save is an unconditional
        # put): a plain UPDATE would silently drop a write if the row were absent.
        _use_tenant(self._conn, artifact.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {_TABLE} "
                "(artifact_id, tenant_id, artifact_type, status, created_by, reviewer_id, "
                "reviewer_group, source_document_ids, source_citations, payload, audit_log_ref, "
                "created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,COALESCE(%s::timestamptz,now()),now()) "
                "ON CONFLICT (artifact_id) DO UPDATE SET "
                "artifact_type=EXCLUDED.artifact_type, status=EXCLUDED.status, "
                "created_by=EXCLUDED.created_by, reviewer_id=EXCLUDED.reviewer_id, "
                "reviewer_group=EXCLUDED.reviewer_group, "
                "source_document_ids=EXCLUDED.source_document_ids, "
                "source_citations=EXCLUDED.source_citations, payload=EXCLUDED.payload, "
                "audit_log_ref=EXCLUDED.audit_log_ref, updated_at=now()",
                _insert_params(artifact),
            )

    def get(self, tenant_id: str, artifact_id: str) -> DraftArtifact | None:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE tenant_id=%s AND artifact_id=%s",
                (tenant_id, artifact_id),
            )
            row = cur.fetchone()
        return _row_to_artifact(row) if row is not None else None

    def list(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        reviewer_id: str | None = None,
    ) -> list[DraftArtifact]:
        _use_tenant(self._conn, tenant_id)
        sql = _SELECT + " WHERE tenant_id=%s"
        params: list[object] = [tenant_id]
        if status:
            sql += " AND status=%s"
            params.append(status)
        if reviewer_id:
            sql += " AND reviewer_id=%s"
            params.append(reviewer_id)
        sql += " ORDER BY created_at DESC, artifact_id DESC"
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [_row_to_artifact(r) for r in rows]


def _payload(artifact: DraftArtifact) -> str:
    blob = {name: getattr(artifact, name) for name in _PAYLOAD_FIELDS}
    blob["content"] = artifact.content
    return json.dumps(blob, sort_keys=True, default=str)


def _insert_params(artifact: DraftArtifact) -> tuple:
    return (
        artifact.artifact_id,
        artifact.tenant_id,
        artifact.type.value,
        artifact.status.value,
        artifact.created_by.value if artifact.created_by is not None else "ai",
        artifact.reviewer_id,
        artifact.reviewer_group,
        list(artifact.source_document_ids),
        json.dumps(list(artifact.source_citations)),
        _payload(artifact),
        artifact.audit_log_ref,
        artifact.created_at,
    )


def _created_at_iso(value) -> str | None:
    """Normalize a timestamptz read-back to a UTC ISO string so it matches the in-memory store's
    representation regardless of the session timezone."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        tz = getattr(value, "tzinfo", None)
        if tz is not None:
            from datetime import timezone

            value = value.astimezone(timezone.utc)
        return value.isoformat()
    return value


def _row_to_artifact(row) -> DraftArtifact:
    (
        artifact_id,
        tenant_id,
        artifact_type,
        status,
        created_by,
        reviewer_id,
        reviewer_group,
        source_document_ids,
        source_citations,
        payload,
        audit_log_ref,
        created_at,
    ) = row
    payload = payload or {}
    content = payload.get("content") or {}
    return DraftArtifact(
        tenant_id=tenant_id,
        artifact_id=artifact_id,
        type=DraftType(artifact_type),
        collection_id=payload.get("collection_id"),
        status=DraftStatus(status),
        source_citations=tuple(source_citations or ()),
        source_document_ids=tuple(source_document_ids or ()),
        template_id=payload.get("template_id"),
        created_by=CreatedBy(created_by) if created_by else None,
        created_at=_created_at_iso(created_at),
        audit_log_ref=audit_log_ref,
        reviewer_id=reviewer_id,
        reviewer_role=payload.get("reviewer_role"),
        reviewer_group=reviewer_group,
        assigned_at=payload.get("assigned_at"),
        reviewed_at=payload.get("reviewed_at"),
        review_comment=payload.get("review_comment"),
        approval_decision=payload.get("approval_decision"),
        review_status=payload.get("review_status"),
        content=dict(content),
    )
