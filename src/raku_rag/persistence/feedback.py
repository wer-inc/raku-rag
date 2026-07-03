"""★G3a answer_feedback — durable 👍/👎 answer feedback (0023, RLS-forced).

Follows the lexicon/chatbot persistence precedent: every Postgres query runs after
``_use_tenant`` so RLS enforces isolation even if a WHERE clause is wrong. Comments are
PII-redacted with the observability Redactor BEFORE write (same stance as audit_logs), in
``build_feedback_record`` so both the in-memory and Postgres repositories store redacted text.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from raku_rag.observability.redaction import Redactor

_redactor = Redactor()

# Older web clients encode the reason category / citation target inside the free-text comment
# ("answer:needs_improvement reason:wrong_evidence", "citation:doc/chunk verdict:incorrect").
# Fall back to parsing those so pre-existing callers still land structured rows.
_REASON_IN_COMMENT = re.compile(r"\breason:([A-Za-z0-9_\-]+)")
_CITATION_IN_COMMENT = re.compile(r"\bcitation:(\S+)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rating_label(score: int) -> str:
    """Map the client's 1-5 score onto the up/down/neutral taxonomy the queue filters on."""
    if score >= 4:
        return "up"
    if 1 <= score <= 2:
        return "down"
    return "neutral"


def _new_feedback_id(tenant_id: str, actor_id: str, answer_id: str) -> str:
    digest = hashlib.sha256(
        f"{tenant_id}:{actor_id}:{answer_id}:{uuid.uuid4().hex}".encode()
    ).hexdigest()[:12]
    return f"fb_{digest}"


def build_feedback_record(
    tenant_id: str,
    *,
    actor_id: str,
    answer_id: str = "",
    evaluation_run_id: str = "",
    subject: str = "user",
    score: int = 0,
    comment: str = "",
    reason_code: str = "",
    citation_id: str | None = None,
) -> dict:
    """Normalize one feedback submission into the durable row shape (redacted, categorized)."""
    subject = subject if subject in ("user", "eval_job") else "user"
    if not reason_code:
        match = _REASON_IN_COMMENT.search(comment)
        reason_code = match.group(1) if match else ""
    if not citation_id:
        match = _CITATION_IN_COMMENT.search(comment)
        citation_id = match.group(1) if match else None
    return {
        "feedback_id": _new_feedback_id(tenant_id, actor_id, answer_id),
        "tenant_id": tenant_id,
        "answer_id": answer_id,
        "evaluation_run_id": evaluation_run_id,
        "subject": subject,
        "rating": rating_label(score),
        "score": int(score),
        "reason_code": reason_code,
        "comment": _redactor.redact(comment),
        "actor_id": actor_id,
        "citation_id": citation_id,
        "created_at": _now(),
    }


@dataclass
class InMemoryFeedbackRepository:
    _items: list[dict] = field(default_factory=list)

    def create(self, tenant_id: str, **kwargs) -> dict:
        record = build_feedback_record(tenant_id, **kwargs)
        self._items.append(record)
        return dict(record)

    def list(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        rating_filter: str | None = None,
    ) -> list[dict]:
        rows = [
            dict(item)
            for item in reversed(self._items)
            if item["tenant_id"] == tenant_id
            and (rating_filter is None or item["rating"] == rating_filter)
        ]
        return rows[offset : offset + limit]


_COLUMNS = (
    "feedback_id",
    "correlation_id",
    "evaluation_run_id",
    "subject",
    "rating",
    "score",
    "reason_code",
    "comment",
    "actor_id",
    "citation_id",
    "created_at",
)


class PostgresFeedbackRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def create(self, tenant_id: str, **kwargs) -> dict:
        from raku_rag.persistence.postgres import _use_tenant

        record = build_feedback_record(tenant_id, **kwargs)
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (tenant_id,),
            )
            cur.execute(
                "INSERT INTO answer_feedback "
                "(feedback_id, tenant_id, correlation_id, evaluation_run_id, subject, rating, "
                "score, reason_code, comment, actor_id, citation_id, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::timestamptz)",
                (
                    record["feedback_id"],
                    tenant_id,
                    record["answer_id"],
                    record["evaluation_run_id"],
                    record["subject"],
                    record["rating"],
                    record["score"],
                    record["reason_code"],
                    record["comment"],
                    record["actor_id"],
                    record["citation_id"],
                    record["created_at"],
                ),
            )
        return dict(record)

    def list(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        rating_filter: str | None = None,
    ) -> list[dict]:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        sql = "SELECT " + ", ".join(_COLUMNS) + " FROM answer_feedback WHERE tenant_id = %s"
        params: list = [tenant_id]
        if rating_filter is not None:
            sql += " AND rating = %s"
            params.append(rating_filter)
        sql += " ORDER BY created_at DESC, feedback_id LIMIT %s OFFSET %s"
        params.extend([max(0, int(limit)), max(0, int(offset))])
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        out: list[dict] = []
        for row in rows:
            item = dict(zip(_COLUMNS, row))
            item["answer_id"] = item.pop("correlation_id")
            item["tenant_id"] = tenant_id
            created_at = item.get("created_at")
            if isinstance(created_at, datetime):
                item["created_at"] = created_at.isoformat()
            out.append(item)
        return out
