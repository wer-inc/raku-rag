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
import hashlib
from typing import Sequence

try:
    # psycopg is a production-adapter dependency. The stdlib-only Tier A gate imports this module
    # transitively (apps/answer-service → raku_rag.production → here) without psycopg installed, so
    # defer the hard requirement to actual Postgres use and keep the module importable under stdlib.
    import psycopg
    from psycopg.types.json import Json
except ModuleNotFoundError:  # pragma: no cover - exercised by the stdlib-only Tier A gate
    psycopg = None  # type: ignore[assignment]
    Json = None  # type: ignore[assignment]

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import (
    ACLGrant,
    Chunk,
    Document,
    IdentityClaims,
    Modality,
    ScopeType,
    ScoredChunk,
    SubjectType,
)
from raku_rag.interfaces.base import Vector, VectorStore, VisibilityPredicate
from raku_rag.workers.ingestion import (
    DocumentProcessingState,
    IngestionJobMessage,
    IngestionRun,
    SourceSyncState,
)

_APP_ROLE = "raku_app"
# child → parent order, so TRUNCATE ... CASCADE is unambiguous.
_CORE_TABLES = (
    "audit_logs",
    "acl_grants",
    "document_processing_states",
    "ingestion_runs",
    "source_sync_states",
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
    if psycopg is None:  # pragma: no cover - clear failure if used without the optional dependency
        raise RuntimeError(
            "psycopg is required for the Postgres adapters; install 'psycopg[binary]'."
        )
    conn = psycopg.connect(dsn, autocommit=True)
    with conn.cursor() as cur:
        if reset:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename = ANY(%s)",
                (list(_CORE_TABLES),),
            )
            existing = {r[0] for r in cur.fetchall()}
            reset_tables = [t for t in _CORE_TABLES if t in existing]
            if reset_tables:
                cur.execute("TRUNCATE " + ", ".join(reset_tables) + " CASCADE")
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


def _ensure_collection_parent(conn: psycopg.Connection, tenant_id: str, collection_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING", (tenant_id,)
        )
        cur.execute(
            "INSERT INTO collections (collection_id, tenant_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (collection_id, tenant_id),
        )


def _ensure_doc_parents(
    conn: psycopg.Connection,
    tenant_id: str,
    collection_id: str,
    document_id: str,
    source_id: str = "",
) -> None:
    """Upsert the FK parents (tenant → collection → document stub) so chunk/doc writes never violate FKs.

    The in-memory store has no FKs; the production schema does. Defensive ON CONFLICT DO NOTHING keeps
    the in-memory call order (chunks upserted before ``registry.put``) working against Postgres.
    """
    _ensure_collection_parent(conn, tenant_id, collection_id)
    with conn.cursor() as cur:
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


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _row_to_ingestion_run(row) -> IngestionRun:
    return IngestionRun(
        ingestion_run_id=row[0],
        tenant_id=row[1],
        collection_id=row[2],
        source_id=row[3] or "",
        document_id=row[4] or "",
        type=row[5],
        trigger=row[6],
        status=row[7],
        idempotency_key=row[8],
        document_ref=row[9] or "",
        content_type=row[10] or "text/plain",
        sqs_message_id=row[11] or "",
        retry_count=row[12],
        chunk_count=row[13],
        failure_reason=row[14] or "",
        dagster_run_id=row[15] or "",
        started_at=_iso(row[16]),
        finished_at=_iso(row[17]),
        created_at=_iso(row[18]),
        updated_at=_iso(row[19]),
    )


def _row_to_processing_state(row) -> DocumentProcessingState:
    return DocumentProcessingState(
        tenant_id=row[0],
        document_id=row[1],
        ingestion_run_id=row[2],
        collection_id=row[3],
        source_id=row[4] or "",
        status=row[5],
        content_checksum=row[6] or "",
        parser_version=row[7] or "",
        chunking_config_version=row[8] or "",
        embedding_model_version=row[9] or "",
        chunk_count=row[10],
        failure_reason=row[11] or "",
        updated_at=_iso(row[12]),
    )


def _row_to_source_sync_state(row) -> SourceSyncState:
    return SourceSyncState(
        source_id=row[0],
        tenant_id=row[1],
        collection_id=row[2],
        status=row[3],
        last_manifest_checksum=row[4] or "",
        last_ingestion_run_id=row[5] or "",
        observed_count=row[6],
        changed_count=row[7],
        deleted_count=row[8],
        skipped_count=row[9],
        failed_count=row[10],
        last_synced_at=_iso(row[11]),
        created_at=_iso(row[12]),
        updated_at=_iso(row[13]),
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

    def visual_chunks_for_asset(self, tenant_id: str, asset_id: str) -> tuple[Chunk, ...]:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id, tenant_id, document_id, collection_id, modality, text, token_count, "
                "position, heading_path, offset_mapping, metadata, embedding_model_version, tombstone "
                "FROM chunks WHERE tombstone = false AND modality = 'visual' "
                "AND metadata->>'asset_id' = %s ORDER BY position, chunk_id",
                (asset_id,),
            )
            rows = cur.fetchall()
        return tuple(_row_to_chunk(row) for row in rows)

    def visual_chunks_for_document(self, tenant_id: str, document_id: str) -> tuple[Chunk, ...]:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id, tenant_id, document_id, collection_id, modality, text, token_count, "
                "position, heading_path, offset_mapping, metadata, embedding_model_version, tombstone "
                "FROM chunks WHERE tombstone = false AND modality = 'visual' "
                "AND document_id = %s ORDER BY position, chunk_id",
                (document_id,),
            )
            rows = cur.fetchall()
        return tuple(_row_to_chunk(row) for row in rows)


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
        _ensure_doc_parents(
            self._conn, doc.tenant_id, doc.collection_id, doc.document_id, doc.source_id
        )
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
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (grant.tenant_id,),
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
        return [ACLGrant(r[0], ScopeType(r[1]), r[2], SubjectType(r[3]), r[4], r[5]) for r in rows]

    def visibility(self, p):
        self._grants = self._load(p.tenant_id)
        return super().visibility(p)

    def can_read_document(self, p: IdentityClaims, doc: Document) -> bool:
        self._grants = self._load(p.tenant_id)
        return super().can_read_document(p, doc)


class PostgresIngestionRunStore:
    """Postgres-backed store with the same surface as ``IngestionRunStore``.

    The worker can use this in production without changing queue/connector/ingestion orchestration.
    RLS applies to every operation through ``_use_tenant``.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create_queued(
        self, message: IngestionJobMessage, *, trigger: str = "sqs", run_type: str = "upload_ingest"
    ) -> tuple[IngestionRun, bool]:
        _use_tenant(self._conn, message.tenant_id)
        _ensure_collection_parent(self._conn, message.tenant_id, message.collection_id)
        existing = self.get_by_idempotency_key(message.tenant_id, message.idempotency_key)
        if existing is not None:
            return existing, False

        run_id = _stable_id("ing", message.tenant_id, message.idempotency_key)
        state_id = _stable_id("dps", message.tenant_id, message.document_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_runs (ingestion_run_id, tenant_id, collection_id, source_id, "
                "document_id, idempotency_key, document_ref, content_type, type, trigger, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued')",
                (
                    run_id,
                    message.tenant_id,
                    message.collection_id,
                    message.source_id,
                    message.document_id,
                    message.idempotency_key,
                    message.document_ref,
                    message.content_type,
                    run_type,
                    trigger,
                ),
            )
            cur.execute(
                "INSERT INTO document_processing_states (processing_state_id, tenant_id, "
                "collection_id, document_id, source_id, ingestion_run_id, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,'queued') "
                "ON CONFLICT (tenant_id, document_id) DO UPDATE SET "
                "ingestion_run_id=EXCLUDED.ingestion_run_id, status='queued', "
                "failure_reason='', updated_at=now()",
                (
                    state_id,
                    message.tenant_id,
                    message.collection_id,
                    message.document_id,
                    message.source_id,
                    run_id,
                ),
            )
        run = self.get(run_id)
        assert run is not None
        return run, True

    def get(self, ingestion_run_id: str) -> IngestionRun | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT ingestion_run_id, tenant_id, collection_id, source_id, document_id, type, "
                "trigger, status, idempotency_key, document_ref, content_type, sqs_message_id, "
                "retry_count, chunk_count, failure_reason, dagster_run_id, started_at, finished_at, "
                "created_at, updated_at "
                "FROM ingestion_runs WHERE ingestion_run_id = %s",
                (ingestion_run_id,),
            )
            row = cur.fetchone()
        return _row_to_ingestion_run(row) if row else None

    def get_for_tenant(self, tenant_id: str, ingestion_run_id: str) -> IngestionRun | None:
        _use_tenant(self._conn, tenant_id)
        return self.get(ingestion_run_id)

    def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str) -> IngestionRun | None:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT ingestion_run_id, tenant_id, collection_id, source_id, document_id, type, "
                "trigger, status, idempotency_key, document_ref, content_type, sqs_message_id, "
                "retry_count, chunk_count, failure_reason, dagster_run_id, started_at, finished_at, "
                "created_at, updated_at "
                "FROM ingestion_runs WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            row = cur.fetchone()
        return _row_to_ingestion_run(row) if row else None

    def processing_state(self, tenant_id: str, document_id: str) -> DocumentProcessingState | None:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, document_id, ingestion_run_id, collection_id, source_id, status, "
                "content_checksum, parser_version, chunking_config_version, embedding_model_version, "
                "chunk_count, failure_reason, updated_at "
                "FROM document_processing_states WHERE document_id = %s",
                (document_id,),
            )
            row = cur.fetchone()
        return _row_to_processing_state(row) if row else None

    def source_sync_state(self, tenant_id: str, source_id: str) -> SourceSyncState | None:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, tenant_id, collection_id, status, last_manifest_checksum, "
                "last_ingestion_run_id, observed_count, changed_count, deleted_count, skipped_count, "
                "failed_count, last_synced_at, created_at, updated_at "
                "FROM source_sync_states WHERE source_id = %s",
                (source_id,),
            )
            row = cur.fetchone()
        if row:
            return _row_to_source_sync_state(row)

        # Upload-ingest flows do not always materialize a SourceSyncState yet. Provide a read-only
        # projection from recent ingestion runs so the admin UI can still show source-level freshness.
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT ingestion_run_id, tenant_id, collection_id, source_id, document_id, type, "
                "trigger, status, idempotency_key, document_ref, content_type, sqs_message_id, "
                "retry_count, chunk_count, failure_reason, dagster_run_id, started_at, finished_at, "
                "created_at, updated_at "
                "FROM ingestion_runs WHERE source_id = %s ORDER BY created_at DESC",
                (source_id,),
            )
            runs = [_row_to_ingestion_run(r) for r in cur.fetchall()]
        if not runs:
            return None

        latest = runs[0]
        status = {
            "queued": "queued",
            "running": "syncing",
            "failed": "failed",
            "dead_letter": "failed",
        }.get(latest.status, "idle")
        return SourceSyncState(
            source_id=source_id,
            tenant_id=tenant_id,
            collection_id=latest.collection_id,
            status=status,
            last_ingestion_run_id=latest.ingestion_run_id,
            observed_count=len(runs),
            changed_count=sum(1 for r in runs if r.status == "succeeded"),
            failed_count=sum(1 for r in runs if r.status in {"failed", "dead_letter"}),
            last_synced_at=next((r.finished_at for r in runs if r.status == "succeeded"), ""),
            created_at=latest.created_at,
            updated_at=latest.updated_at,
        )

    def list_runs(
        self,
        tenant_id: str,
        *,
        status: str = "",
        source_id: str = "",
        limit: int = 50,
    ) -> list[IngestionRun]:
        _use_tenant(self._conn, tenant_id)
        clauses: list[str] = []
        params: list[object] = []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if source_id:
            clauses.append("source_id = %s")
            params.append(source_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(limit, 200)))
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT ingestion_run_id, tenant_id, collection_id, source_id, document_id, type, "
                "trigger, status, idempotency_key, document_ref, content_type, sqs_message_id, "
                "retry_count, chunk_count, failure_reason, dagster_run_id, started_at, finished_at, "
                "created_at, updated_at FROM ingestion_runs"
                + where
                + " ORDER BY created_at DESC LIMIT %s",
                params,
            )
            return [_row_to_ingestion_run(r) for r in cur.fetchall()]

    def mark_message_id(self, run: IngestionRun, message_id: str) -> None:
        _use_tenant(self._conn, run.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_runs SET sqs_message_id = %s, updated_at = now() "
                "WHERE ingestion_run_id = %s",
                (message_id, run.ingestion_run_id),
            )
        run.sqs_message_id = message_id

    def mark_running(self, run: IngestionRun) -> None:
        self._mark(run, "running", started=True)

    def mark_succeeded(
        self,
        run: IngestionRun,
        *,
        chunk_count: int,
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
    ) -> None:
        self._mark(
            run,
            "succeeded",
            chunk_count=chunk_count,
            content_checksum=content_checksum,
            parser_version=parser_version,
            chunking_config_version=chunking_config_version,
            embedding_model_version=embedding_model_version,
            finished=True,
        )

    def mark_failed(
        self,
        run: IngestionRun,
        *,
        reason: str,
        retry_count: int,
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
    ) -> None:
        self._mark(
            run,
            "failed",
            reason=reason,
            retry_count=retry_count,
            content_checksum=content_checksum,
            parser_version=parser_version,
            chunking_config_version=chunking_config_version,
            embedding_model_version=embedding_model_version,
            finished=True,
        )

    def mark_dead_letter(
        self,
        run: IngestionRun,
        *,
        reason: str,
        retry_count: int,
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
    ) -> None:
        self._mark(
            run,
            "dead_letter",
            reason=reason,
            retry_count=retry_count,
            content_checksum=content_checksum,
            parser_version=parser_version,
            chunking_config_version=chunking_config_version,
            embedding_model_version=embedding_model_version,
            finished=True,
        )

    def _mark(
        self,
        run: IngestionRun,
        status: str,
        *,
        chunk_count: int = 0,
        reason: str = "",
        retry_count: int = 0,
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
        started: bool = False,
        finished: bool = False,
    ) -> None:
        _use_tenant(self._conn, run.tenant_id)
        started_sql = ", started_at = COALESCE(started_at, now())" if started else ""
        finished_sql = ", finished_at = now()" if finished else ""
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_runs SET status=%s, chunk_count=%s, failure_reason=%s, "
                "retry_count=%s, updated_at=now()"
                + started_sql
                + finished_sql
                + " WHERE ingestion_run_id=%s",
                (
                    status,
                    chunk_count or run.chunk_count,
                    reason,
                    retry_count or run.retry_count,
                    run.ingestion_run_id,
                ),
            )
            cur.execute(
                "UPDATE document_processing_states SET status=%s, chunk_count=%s, "
                "failure_reason=%s, content_checksum=COALESCE(NULLIF(%s, ''), content_checksum), "
                "parser_version=COALESCE(NULLIF(%s, ''), parser_version), "
                "chunking_config_version=COALESCE(NULLIF(%s, ''), chunking_config_version), "
                "embedding_model_version=COALESCE(NULLIF(%s, ''), embedding_model_version), "
                "updated_at=now() WHERE tenant_id=%s AND document_id=%s",
                (
                    status,
                    chunk_count,
                    reason,
                    content_checksum,
                    parser_version,
                    chunking_config_version,
                    embedding_model_version,
                    run.tenant_id,
                    run.document_id,
                ),
            )
        run.status = status
        run.chunk_count = chunk_count or run.chunk_count
        run.failure_reason = reason
        run.retry_count = retry_count or run.retry_count
