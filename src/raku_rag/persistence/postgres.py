"""Postgres-backed adapters for the 001 production track — Step 2 "security parity".

These mirror the in-memory MVP adapters (``providers/vectorstores.InMemoryVectorStore``,
``services/ingestion.DocumentRegistry``, ``core/security/acl.AclPolicy``) against the production schema
(``infra/db/migrations/postgres/0001_core_rls.sql``):

- **tenant + tombstone + RLS** are enforced by Postgres; the **ACL hierarchy stays in Python** (the
  reused ``AclPolicy``), applied as a PRE-filter inside ``search`` in the SAME order as the in-memory store
  (tenant → tombstone → ``visible``), so the existing security hard gates pass unchanged (adapter parity).
- Every connection drops to the non-superuser ``raku_app`` role and sets ``app.current_tenant_id`` per
  operation, so **RLS is genuinely exercised** (a superuser would bypass it).
- ranking uses pgvector (``ORDER BY embedding <=> q`` = cosine distance) over the RLS-tenant live set,
  with the ACL filter applied in Python AFTER ranking and BEFORE ``top_k`` — so ``top_k`` never truncates
  before ACL (see ``search``). ``retrieval_score`` = ``1 - cosine_distance`` (the in-memory cosine).
"""
from __future__ import annotations

import json
from typing import Sequence

import psycopg
from psycopg.types.json import Json

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import (
    ACLGrant,
    Chunk,
    Document,
    Modality,
    ScopeType,
    ScoredChunk,
    SubjectType,
)
from raku_rag.interfaces.base import Vector, VectorStore, VisibilityPredicate

_APP_ROLE = "raku_app"
# child → parent order, so TRUNCATE ... CASCADE is unambiguous.
_CORE_TABLES = (
    "audit_logs",
    "acl_grants",
    "chunks",
    "documents",
    "data_sources",
    "collections",
    "query_profiles",
    "tenants",
)


def connect(dsn: str, *, reset: bool = False) -> psycopg.Connection:
    """Open an autocommit connection for the app workload.

    ``reset=True`` (tests only) TRUNCATEs all core tables for a clean slate — done as the connecting
    superuser BEFORE dropping to ``raku_app``. Then ``SET ROLE raku_app`` so RLS applies to every query.
    """
    conn = psycopg.connect(dsn, autocommit=True)
    with conn.cursor() as cur:
        if reset:
            cur.execute("TRUNCATE " + ", ".join(_CORE_TABLES) + " CASCADE")
        cur.execute(f"SET ROLE {_APP_ROLE}")
    return conn


def _use_tenant(conn: psycopg.Connection, tenant_id: str) -> None:
    """Bind the RLS session tenant (``raku.current_tenant_id()`` reads this).

    ``SET`` cannot take a bind parameter; ``set_config(..., is_local=false)`` is the parameterized,
    session-level equivalent.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant_id,))


def _vec_literal(vec: Vector) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _ensure_doc_parents(
    conn: psycopg.Connection, tenant_id: str, collection_id: str, document_id: str, source_id: str = ""
) -> None:
    """Upsert the FK parents (tenant → collection → document stub) so chunk/doc writes never violate FKs.

    The in-memory store has no FKs; the production schema does. Defensive ON CONFLICT DO NOTHING keeps
    the in-memory call order (chunks upserted before ``registry.put``) working against Postgres.
    """
    with conn.cursor() as cur:
        cur.execute("INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING", (tenant_id,))
        cur.execute(
            "INSERT INTO collections (collection_id, tenant_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (collection_id, tenant_id),
        )
        cur.execute(
            "INSERT INTO documents (document_id, tenant_id, collection_id, source_id) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (document_id, tenant_id, collection_id, source_id),
        )


def _load_jsonish(value):
    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else value


def _load_offset_mapping(value):
    om = _load_jsonish(value)
    if not om:
        return None
    return (tuple(om[0]), om[1])


def _iso(ts) -> str:
    return ts.isoformat() if ts is not None else ""


def _row_to_chunk(r) -> Chunk:
    return Chunk(
        chunk_id=r[0],
        tenant_id=r[1],
        document_id=r[2],
        collection_id=r[3],
        modality=Modality(r[4]),
        text=r[5],
        token_count=r[6],
        position=r[7],
        heading_path=tuple(r[8] or ()),
        offset_mapping=_load_offset_mapping(r[9]),
        metadata=_load_jsonish(r[10]) or {},
        embedding_model_version=r[11] or "",
        tombstone=r[12],
    )


class PostgresVectorStore(VectorStore):
    """pgvector-backed ``VectorStore``. Pre-filter order identical to the in-memory store."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn
        self.last_prefiltered_count: int = 0

    def upsert(self, chunks: Sequence[tuple[Chunk, Vector]]) -> None:
        items = list(chunks)
        if not items:
            return
        first = items[0][0]  # ingestion upserts one document's chunks at a time
        _use_tenant(self._conn, first.tenant_id)
        _ensure_doc_parents(self._conn, first.tenant_id, first.collection_id, first.document_id)
        with self._conn.cursor() as cur:
            for chunk, vec in items:
                cur.execute(
                    "INSERT INTO chunks (chunk_id, tenant_id, document_id, collection_id, modality, "
                    "text, token_count, position, heading_path, offset_mapping, metadata, "
                    "embedding_model_version, embedding, tombstone) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s) "
                    "ON CONFLICT (chunk_id) DO UPDATE SET text=EXCLUDED.text, "
                    "embedding=EXCLUDED.embedding, tombstone=EXCLUDED.tombstone, "
                    "position=EXCLUDED.position, metadata=EXCLUDED.metadata",
                    (
                        chunk.chunk_id,
                        chunk.tenant_id,
                        chunk.document_id,
                        chunk.collection_id,
                        chunk.modality.value,
                        chunk.text,
                        chunk.token_count,
                        chunk.position,
                        list(chunk.heading_path),
                        Json(chunk.offset_mapping),
                        Json(chunk.metadata),
                        chunk.embedding_model_version,
                        _vec_literal(vec),
                        chunk.tombstone,
                    ),
                )

    def search(
        self, tenant_id: str, query_vec: Vector, *, visible: VisibilityPredicate, top_k: int
    ) -> list[ScoredChunk]:
        """pgvector distance ranking, ACL post-filter, THEN top_k.

        Step 3 moves ranking to pgvector (``ORDER BY embedding <=> q`` = cosine distance) over the
        RLS-tenant + live set, but deliberately applies NO SQL ``LIMIT`` before the Python ACL filter:
        a ``LIMIT k`` in SQL would truncate the candidate set before ACL and silently drop visible
        chunks that rank just past it. So we rank-order the whole visible-tenant set, drop non-visible
        chunks in Python (reused AclPolicy, order preserved), set ``last_prefiltered_count``, and only
        then take ``top_k`` — identical semantics to the in-memory store. ``retrieval_score`` =
        ``1 - cosine_distance`` = the cosine similarity the in-memory store reports (ranking parity).
        """
        _use_tenant(self._conn, tenant_id)  # RLS scopes the tenant
        qlit = _vec_literal(query_vec)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id, tenant_id, document_id, collection_id, modality, text, token_count, "
                "position, heading_path, offset_mapping, metadata, embedding_model_version, tombstone, "
                "(embedding <=> %s::vector) AS distance FROM chunks WHERE tombstone = false "
                "ORDER BY embedding <=> %s::vector, chunk_id",  # cosine-distance rank; chunk_id breaks ties
                (qlit, qlit),
            )
            rows = cur.fetchall()
        candidates: list[ScoredChunk] = []
        for r in rows:  # rows already in best-first distance order
            chunk = _row_to_chunk(r)
            if not visible(chunk):  # ACL post-filter in Python — AFTER ranking, BEFORE top_k
                continue
            candidates.append(ScoredChunk(chunk=chunk, retrieval_score=1.0 - float(r[13])))
        self.last_prefiltered_count = len(candidates)
        return candidates[:top_k]

    def set_tombstone(self, tenant_id: str, document_id: str, value: bool) -> int:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE chunks SET tombstone = %s WHERE document_id = %s", (value, document_id)
            )
            return cur.rowcount

    def purge(self, tenant_id: str, document_id: str) -> int:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            return cur.rowcount


class PostgresDocumentRegistry:
    """Document metadata in the ``documents`` table (mirrors ``services.ingestion.DocumentRegistry``)."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def get(self, tenant_id: str, document_id: str) -> Document | None:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, collection_id, document_id, source_id, version, checksum, metadata, "
                "created_at, updated_at, indexed_at, tombstone FROM documents WHERE document_id = %s",
                (document_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Document(
            tenant_id=row[0],
            collection_id=row[1],
            document_id=row[2],
            source_id=row[3] or "",
            version=row[4],
            checksum=row[5] or "",
            metadata=_load_jsonish(row[6]) or {},
            created_at=_iso(row[7]),
            updated_at=_iso(row[8]),
            indexed_at=_iso(row[9]),
            tombstone=row[10],
        )

    def put(self, doc: Document) -> None:
        _use_tenant(self._conn, doc.tenant_id)
        _ensure_doc_parents(self._conn, doc.tenant_id, doc.collection_id, doc.document_id, doc.source_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO documents (document_id, tenant_id, collection_id, source_id, version, "
                "checksum, metadata, indexed_at, tombstone) VALUES (%s,%s,%s,%s,%s,%s,%s,now(),%s) "
                "ON CONFLICT (document_id) DO UPDATE SET source_id=EXCLUDED.source_id, "
                "version=EXCLUDED.version, checksum=EXCLUDED.checksum, metadata=EXCLUDED.metadata, "
                "indexed_at=now(), tombstone=EXCLUDED.tombstone, updated_at=now()",
                (
                    doc.document_id,
                    doc.tenant_id,
                    doc.collection_id,
                    doc.source_id,
                    doc.version,
                    doc.checksum,
                    Json(doc.metadata),
                    doc.tombstone,
                ),
            )


class PostgresAclPolicy(AclPolicy):
    """Reuses the Python ``AclPolicy`` decision logic; grants live in the ``acl_grants`` table.

    ``visibility`` loads the principal's tenant grants from Postgres into ``_grants`` once per call, so the
    inherited deny-by-default ``can_read`` predicate runs exactly as in the MVP — only the grant store moved.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        super().__init__([])
        self._conn = conn

    def add(self, grant: ACLGrant) -> None:
        _use_tenant(self._conn, grant.tenant_id)
        grant_id = ":".join(
            (
                grant.tenant_id,
                grant.scope_type.value,
                grant.scope_id,
                grant.subject_type.value,
                grant.subject_id,
            )
        )
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING", (grant.tenant_id,)
            )
            cur.execute(
                "INSERT INTO acl_grants (grant_id, tenant_id, scope_type, scope_id, subject_type, "
                "subject_id, permission) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (grant_id) DO NOTHING",
                (
                    grant_id,
                    grant.tenant_id,
                    grant.scope_type.value,
                    grant.scope_id,
                    grant.subject_type.value,
                    grant.subject_id,
                    grant.permission,
                ),
            )

    def _load(self, tenant_id: str) -> list[ACLGrant]:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, scope_type, scope_id, subject_type, subject_id, permission "
                "FROM acl_grants"
            )
            rows = cur.fetchall()
        return [
            ACLGrant(r[0], ScopeType(r[1]), r[2], SubjectType(r[3]), r[4], r[5]) for r in rows
        ]

    def visibility(self, p):
        self._grants = self._load(p.tenant_id)
        return super().visibility(p)
