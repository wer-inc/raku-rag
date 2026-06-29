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
import os
import time
import uuid
from typing import Mapping, Sequence

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
from raku_rag.core.hybrid_retrieval import (
    HOT_IDENTIFIER_FIELDS,
    lexical_match_score,
    lexical_query_terms,
    METADATA_EXACT_MATCH_SCORE,
    NESTED_METADATA_KEYS,
    query_identifiers,
)
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
from raku_rag.dagster.run_url import dagster_run_url
from raku_rag.interfaces.base import Vector, VectorStore, VisibilityPredicate
from raku_rag.observability.audit import AuditEvent, sanitize_audit_event
from raku_rag.persistence.control_plane import (
    AssetMaterializationRef,
    DocumentProcessingProjection,
    SourceSyncStatusProjection,
)
from raku_rag.services.sync import SourceDocumentManifest
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


def _connect_with_retry(dsn: str) -> psycopg.Connection:
    """Open the connection, retrying transient failures on boot.

    On a fresh deploy the DB endpoint may not resolve / accept connections yet (Aurora still coming
    up, brief failover). Rather than crash-loop the container — which trips the ECS deployment circuit
    breaker and rolls the whole stack back — we retry ``psycopg.OperationalError`` (DNS, refused,
    starting up) with backoff for a bounded window. CFN already orders services after the DB, so this
    only absorbs the small remaining gap. Tuneable via RAKU_DB_CONNECT_TIMEOUT_S (default 90).
    """
    deadline_s = float(os.environ.get("RAKU_DB_CONNECT_TIMEOUT_S", "90"))
    delay_s = 1.0
    waited_s = 0.0
    while True:
        try:
            return psycopg.connect(dsn, autocommit=True)
        except psycopg.OperationalError:
            if waited_s >= deadline_s:
                raise
            time.sleep(delay_s)
            waited_s += delay_s
            delay_s = min(delay_s * 2, 10.0)


def connect(dsn: str, *, reset: bool = False) -> psycopg.Connection:
    """Open an autocommit connection for the app workload.

    ``reset=True`` (tests only) TRUNCATEs all core tables for a clean slate — done as the connecting
    superuser BEFORE dropping to ``raku_app``. Then ``SET ROLE raku_app`` so RLS applies to every query.
    """
    if psycopg is None:  # pragma: no cover - clear failure if used without the optional dependency
        raise RuntimeError(
            "psycopg is required for the Postgres adapters; install 'psycopg[binary]'."
        )
    conn = _connect_with_retry(dsn)
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
            _repair_reset_schema(cur, existing)
        _set_app_role(conn, cur)
    return conn


def _repair_reset_schema(cur: "psycopg.Cursor", existing: set[str]) -> None:
    """Keep reset=True test databases compatible with additive migration drift.

    Local Tier-B databases can outlive migration edits. Because reset=True already truncates the core
    tables, it is safe to re-assert compatibility constraints before dropping to the RLS app role.
    Production still relies on migrations; this helper only runs on explicit test resets.
    """

    if "source_sync_states" in existing:
        cur.execute(
            "ALTER TABLE source_sync_states DROP CONSTRAINT IF EXISTS source_sync_states_pkey"
        )
        cur.execute(
            "ALTER TABLE source_sync_states "
            "ADD CONSTRAINT source_sync_states_pkey PRIMARY KEY (tenant_id, source_id)"
        )
        cur.execute(
            "ALTER TABLE source_sync_states "
            "DROP CONSTRAINT IF EXISTS source_sync_states_status_check"
        )
        cur.execute(
            "ALTER TABLE source_sync_states ADD CONSTRAINT source_sync_states_status_check "
            "CHECK (status IN ('idle', 'queued', 'observing', 'syncing', 'succeeded', "
            "'partially_succeeded', 'failed'))"
        )
    if "ingestion_runs" in existing:
        cur.execute(
            "ALTER TABLE ingestion_runs "
            "ADD COLUMN IF NOT EXISTS async_provider text NOT NULL DEFAULT '', "
            "ADD COLUMN IF NOT EXISTS async_job_id text NOT NULL DEFAULT '', "
            "ADD COLUMN IF NOT EXISTS async_job_status text NOT NULL DEFAULT ''"
        )
    if "provider_policies" in existing:
        cur.execute(
            "ALTER TABLE provider_policies "
            "ADD COLUMN IF NOT EXISTS allowed_layout_providers text[] NOT NULL "
            "DEFAULT ARRAY['aws_textract','tesseract','customer_managed']::text[], "
            "ADD COLUMN IF NOT EXISTS allowed_structured_providers text[] NOT NULL "
            "DEFAULT ARRAY['aws_textract','customer_managed']::text[], "
            "ADD COLUMN IF NOT EXISTS allowed_visual_embedding_providers text[] NOT NULL "
            "DEFAULT ARRAY['bedrock','customer_managed']::text[], "
            "ADD COLUMN IF NOT EXISTS allowed_vlm_providers text[] NOT NULL "
            "DEFAULT ARRAY['bedrock','customer_managed']::text[], "
            "ADD COLUMN IF NOT EXISTS allowed_caption_providers text[] NOT NULL "
            "DEFAULT ARRAY['bedrock','customer_managed']::text[], "
            "ADD COLUMN IF NOT EXISTS opt_in_status_by_family jsonb NOT NULL DEFAULT '{}'::jsonb"
        )


def _set_app_role(conn: "psycopg.Connection", cur: "psycopg.Cursor") -> None:
    """``SET ROLE raku_app``, bootstrapping the role on first boot if needed.

    On a fresh deploy the services start before the migrations have run, so ``raku_app`` may not exist
    yet — or it exists but the connecting (non-superuser) user is not a member, so ``SET ROLE`` is
    refused (the Aurora master is rds_superuser, NOT a true superuser, so membership is required).
    Either way we crash-loop the container and trip the ECS circuit breaker. To break that deadlock we
    create the NOLOGIN role and grant it to the current user, then retry. This is idempotent and
    fail-closed: ``raku_app`` has no table privileges until the migrations grant them, so nothing the
    app does before migration can bypass RLS. (autocommit → a failed statement does not poison the rest.)
    """
    try:
        cur.execute(f"SET ROLE {_APP_ROLE}")
        return
    except (
        # role absent: "role \"raku_app\" does not exist" is SQLSTATE 22023 (InvalidParameterValue),
        # not 42704 — both are caught so the bootstrap covers either Postgres phrasing.
        psycopg.errors.InvalidParameterValue,
        psycopg.errors.UndefinedObject,
        # role exists but the connecting (non-superuser) user is not a member.
        psycopg.errors.InsufficientPrivilege,
    ):
        pass
    # _APP_ROLE is a fixed module constant (not user input), safe to inline.
    cur.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN "
        f"CREATE ROLE {_APP_ROLE} NOLOGIN; END IF; END $$;"
    )
    cur.execute(f"GRANT {_APP_ROLE} TO CURRENT_USER")
    cur.execute(f"SET ROLE {_APP_ROLE}")


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


def _json_mapping(value) -> Mapping[str, object]:
    loaded = _load_jsonish(value)
    return loaded if isinstance(loaded, Mapping) else {}


def _load_offset_mapping(value):
    om = _load_jsonish(value)
    if not om:
        return None
    return (tuple(om[0]), om[1])


def _iso(ts) -> str:
    if ts is None:
        return ""
    return ts if isinstance(ts, str) else ts.isoformat()


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


def _metadata_identifier_conditions() -> tuple[str, int]:
    conditions: list[str] = []
    for alias in ("c", "d"):
        for field in HOT_IDENTIFIER_FIELDS:
            expressions = [f"{alias}.metadata->>'{field}'"]
            expressions.extend(
                f"{alias}.metadata->'{nested}'->>'{field}'" for nested in NESTED_METADATA_KEYS
            )
            for expr in expressions:
                conditions.append(f"lower({expr}) = ANY(%s::text[])")
                conditions.append(
                    f"regexp_replace(lower({expr}), '[^a-z0-9]+', '', 'g') = ANY(%s::text[])"
                )
    return " OR ".join(conditions), len(conditions)


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
        async_provider=row[16] or "",
        async_job_id=row[17] or "",
        async_job_status=row[18] or "",
        started_at=_iso(row[19]),
        finished_at=_iso(row[20]),
        created_at=_iso(row[21]),
        updated_at=_iso(row[22]),
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


def _audit_metadata_str(metadata: dict, key: str) -> str:
    value = metadata.get(key, "")
    return value if isinstance(value, str) else ""


def _audit_metadata_bool(metadata: dict, key: str) -> bool:
    value = metadata.get(key, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return False


def _audit_metadata_tuple(metadata: dict, key: str) -> tuple[str, ...]:
    value = metadata.get(key, ())
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _row_to_audit_event(row) -> AuditEvent:
    metadata = {
        "log_id": row[0],
        "request_id": row[3] or "",
        "trace_id": row[4] or "",
        "actor_role": row[7] or "",
        "actor_group": row[8] or "",
        "app_id": row[9] or "",
        "api_client_id": row[10] or "",
        "actor_type": row[11] or "",
        "policy_version": row[17] or "",
        "approval_status_at_use": row[18] or "",
        "citation_ids": tuple(row[19] or ()),
        "retrieval_profile_id": row[22] or "",
        "provider_policy_id": row[23] or "",
        "pii_redaction_applied": bool(row[24]),
        "secret_redaction_applied": bool(row[25]),
        "logging_policy_id": row[26] or "",
        "raw_content_stored": bool(row[27]),
    }
    return AuditEvent(
        tenant_id=row[1],
        created_at=_iso(row[2]),
        correlation_id=row[5] or "",
        actor_id=row[6] or "",
        action=row[12],
        resource_type=row[13] or "",
        resource_id=row[14] or "",
        decision=row[15],
        reason=row[16] or "",
        document_ids=tuple(row[20] or ()),
        chunk_ids=tuple(row[21] or ()),
        metadata=metadata,
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

    def __init__(self, conn: psycopg.Connection, *, embedding_dim: int = 256) -> None:
        self._conn = conn
        self._embedding_dim = embedding_dim
        self.last_prefiltered_count: int = 0

    def upsert(self, chunks: Sequence[tuple[Chunk, Vector]]) -> None:
        items = list(chunks)
        if not items:
            return
        for _chunk, vec in items:
            if len(vec) != self._embedding_dim:
                raise ValueError(
                    "embedding dimension mismatch for chunks table: "
                    f"expected {self._embedding_dim}, got {len(vec)}"
                )
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

    def iter_items(self) -> tuple[tuple[Chunk, Vector], ...]:
        """Bulk (chunk, vector) scan for the connection's current RLS tenant context.

        Mirrors the in-memory ``iter_items`` seam used by the manufacturing metadata propagation
        (``propagate_to_chunks``) and the ACL-denial survey. RLS scopes the rows to the connection's
        current ``app.current_tenant_id`` (set with ``is_local=false`` by the preceding tenant-scoped
        operation in these flows, so it persists for the session); each caller re-filters by
        tenant/document. The embedding is NOT re-materialized — both callers ignore the vector — so an
        empty placeholder vector is returned to honor the ``(Chunk, Vector)`` shape.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id, tenant_id, document_id, collection_id, modality, text, "
                "token_count, position, heading_path, offset_mapping, metadata, "
                "embedding_model_version, tombstone FROM chunks ORDER BY chunk_id"
            )
            rows = cur.fetchall()
        empty: Vector = []
        return tuple((_row_to_chunk(r), empty) for r in rows)

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

    def metadata_exact_matches(
        self,
        tenant_id: str,
        query: str,
        *,
        visible: VisibilityPredicate,
        top_k: int,
    ) -> list[ScoredChunk]:
        """Metadata identifier leg for the deployed hybrid retrieval path.

        ACL remains the same Python ``visible`` predicate used by vector search. The SQL leg only
        narrows to tenant/RLS-live chunks whose chunk or document metadata names an exact business
        identifier from the query.
        """
        identifiers = query_identifiers(query)
        if not identifiers or top_k <= 0:
            return []
        conditions, parameter_count = _metadata_identifier_conditions()
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT c.chunk_id, c.tenant_id, c.document_id, c.collection_id, c.modality, "
                "c.text, c.token_count, c.position, c.heading_path, c.offset_mapping, "
                "c.metadata, c.embedding_model_version, c.tombstone "
                "FROM chunks c JOIN documents d "
                "ON d.document_id = c.document_id AND d.tenant_id = c.tenant_id "
                "WHERE c.tenant_id = %s AND c.tombstone = false AND d.tombstone = false "
                f"AND ({conditions}) ORDER BY c.position, c.chunk_id",
                (tenant_id, *[list(identifiers) for _ in range(parameter_count)]),
            )
            rows = cur.fetchall()
        candidates: list[ScoredChunk] = []
        for row in rows:
            chunk = _row_to_chunk(row)
            if not visible(chunk):
                continue
            candidates.append(ScoredChunk(chunk=chunk, retrieval_score=METADATA_EXACT_MATCH_SCORE))
        return candidates[:top_k]

    def lexical_matches(
        self,
        tenant_id: str,
        query: str,
        *,
        visible: VisibilityPredicate,
        top_k: int,
    ) -> list[ScoredChunk]:
        """Lexical keyword leg for deployed hybrid retrieval.

        The SQL predicate narrows to tenant/RLS-live chunks containing at least one query content
        term. The shared Python scorer then applies coverage/density/recency scoring so Tier A and
        Postgres stay behaviorally aligned.
        """
        terms = lexical_query_terms(query)
        if not terms or top_k <= 0:
            return []
        tsquery = " | ".join(f"{term}:*" for term in terms)
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT c.chunk_id, c.tenant_id, c.document_id, c.collection_id, c.modality, "
                "c.text, c.token_count, c.position, c.heading_path, c.offset_mapping, "
                "c.metadata, c.embedding_model_version, c.tombstone, d.metadata "
                "FROM chunks c JOIN documents d "
                "ON d.document_id = c.document_id AND d.tenant_id = c.tenant_id "
                "WHERE c.tenant_id = %s AND c.tombstone = false AND d.tombstone = false "
                "AND to_tsvector('simple', c.text) @@ to_tsquery('simple', %s) "
                "ORDER BY c.position, c.chunk_id",
                (tenant_id, tsquery),
            )
            rows = cur.fetchall()
        candidates: list[ScoredChunk] = []
        for row in rows:
            chunk = _row_to_chunk(row[:13])
            if not visible(chunk):
                continue
            document_metadata = _load_jsonish(row[13]) or {}
            combined_metadata = {**document_metadata, **chunk.metadata}
            score = lexical_match_score(query, chunk.text, combined_metadata)
            if score <= 0:
                continue
            candidates.append(ScoredChunk(chunk=chunk, retrieval_score=score))
        candidates.sort(key=lambda s: (-s.retrieval_score, s.chunk.position, s.chunk.chunk_id))
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


class PostgresAuditSink:
    """Postgres-backed base RAG audit sink.

    The answer path records reference-only events. This adapter persists those events to the
    RLS-protected ``audit_logs`` table so production audits survive process restarts while keeping
    raw prompts, answers, and retrieved context out of the durable audit store.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def record(self, event: AuditEvent) -> AuditEvent:
        redacted = sanitize_audit_event(event)
        metadata = redacted.metadata
        _use_tenant(self._conn, redacted.tenant_id)
        log_id = _audit_metadata_str(metadata, "log_id") or f"aud_{uuid.uuid4().hex}"
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (redacted.tenant_id,),
            )
            cur.execute(
                "INSERT INTO audit_logs (log_id, tenant_id, timestamp, request_id, trace_id, "
                "correlation_id, actor_id, actor_role, actor_group, app_id, api_client_id, "
                "actor_type, action, resource_type, resource_id, decision, reason, "
                "policy_version, approval_status_at_use, citation_ids, document_ids_used, "
                "chunk_ids_used, retrieval_profile_id, provider_policy_id, pii_redaction_applied, "
                "secret_redaction_applied, logging_policy_id, raw_content_stored) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    log_id,
                    redacted.tenant_id,
                    redacted.created_at,
                    _audit_metadata_str(metadata, "request_id"),
                    _audit_metadata_str(metadata, "trace_id"),
                    redacted.correlation_id,
                    redacted.actor_id,
                    _audit_metadata_str(metadata, "actor_role"),
                    _audit_metadata_str(metadata, "actor_group"),
                    _audit_metadata_str(metadata, "app_id"),
                    _audit_metadata_str(metadata, "api_client_id"),
                    _audit_metadata_str(metadata, "actor_type") or "user",
                    redacted.action,
                    redacted.resource_type or "unknown",
                    redacted.resource_id,
                    redacted.decision,
                    redacted.reason,
                    _audit_metadata_str(metadata, "policy_version"),
                    _audit_metadata_str(metadata, "approval_status_at_use"),
                    list(_audit_metadata_tuple(metadata, "citation_ids")),
                    list(redacted.document_ids),
                    list(redacted.chunk_ids),
                    _audit_metadata_str(metadata, "retrieval_profile_id"),
                    _audit_metadata_str(metadata, "provider_policy_id"),
                    _audit_metadata_bool(metadata, "pii_redaction_applied"),
                    _audit_metadata_bool(metadata, "secret_redaction_applied"),
                    _audit_metadata_str(metadata, "logging_policy_id"),
                    _audit_metadata_bool(metadata, "raw_content_stored"),
                ),
            )
        return redacted

    def events(
        self, tenant_id: str | None = None, *, correlation_id: str = ""
    ) -> tuple[AuditEvent, ...]:
        if tenant_id is None:
            raise ValueError("tenant_id is required for Postgres audit reads")
        _use_tenant(self._conn, tenant_id)
        where = ""
        params: tuple[str, ...] = ()
        if correlation_id:
            where = "WHERE correlation_id = %s"
            params = (correlation_id,)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT log_id, tenant_id, timestamp, request_id, trace_id, correlation_id, "
                "actor_id, actor_role, actor_group, app_id, api_client_id, actor_type, action, "
                "resource_type, resource_id, decision, reason, policy_version, "
                "approval_status_at_use, citation_ids, document_ids_used, chunk_ids_used, "
                "retrieval_profile_id, provider_policy_id, pii_redaction_applied, "
                "secret_redaction_applied, logging_policy_id, raw_content_stored "
                f"FROM audit_logs {where} ORDER BY timestamp ASC, log_id ASC",
                params,
            )
            rows = cur.fetchall()
        return tuple(_row_to_audit_event(row) for row in rows)


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

    def list_documents(self, tenant_id: str, *, collection_id: str | None = None) -> list[Document]:
        """Tenant-scoped inventory of live (non-tombstoned) documents (ドキュメント一覧 read view).

        Tenant scoping is enforced by an explicit ``AND tenant_id = %s`` predicate (defense-in-depth):
        the deployed connection runs as a Postgres superuser which BYPASSES RLS, so the ``_use_tenant``
        session var alone would not isolate rows — the WHERE clause makes this method tenant-safe
        regardless of role/RLS. Tombstoned docs are excluded so a source-deleted document never
        resurfaces in the inventory (GAP-S2). No ranking/retrieval.
        """
        _use_tenant(self._conn, tenant_id)
        sql = (
            "SELECT tenant_id, collection_id, document_id, source_id, version, checksum, metadata, "
            "created_at, updated_at, indexed_at, tombstone FROM documents "
            "WHERE tombstone = false AND tenant_id = %s"
        )
        params: list = [tenant_id]
        if collection_id:
            sql += " AND collection_id = %s"
            params.append(collection_id)
        sql += " ORDER BY collection_id, document_id"
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [
            Document(
                tenant_id=r[0],
                collection_id=r[1],
                document_id=r[2],
                source_id=r[3] or "",
                version=r[4],
                checksum=r[5] or "",
                metadata=_load_jsonish(r[6]) or {},
                created_at=_iso(r[7]),
                updated_at=_iso(r[8]),
                indexed_at=_iso(r[9]),
                tombstone=r[10],
            )
            for r in rows
        ]

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


class PostgresProviderPolicyRepository:
    """Read tenant-scoped ProviderPolicy rows for runtime provider gates.

    Missing rows intentionally resolve to the dataclass default with opt-in pending, so production
    provider routers fail closed before external OCR/VLM calls.
    """

    _columns = (
        "provider_policy_id",
        "tenant_id",
        "collection_id",
        "name",
        "status",
        "parser_mode",
        "allowed_parser_providers",
        "allowed_ocr_providers",
        "allowed_layout_providers",
        "allowed_structured_providers",
        "allowed_llm_providers",
        "allowed_embedding_providers",
        "allowed_visual_embedding_providers",
        "allowed_vlm_providers",
        "allowed_caption_providers",
        "allowed_rerank_providers",
        "allowed_regions",
        "zero_retention_required",
        "no_train_required",
        "cross_cloud_processing_allowed",
        "customer_opt_in_required",
        "customer_opt_in_status",
        "opt_in_status_by_family",
        "fallback_policy",
    )
    _json_columns = {"opt_in_status_by_family", "fallback_policy"}

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def _row_to_mapping(self, row) -> dict[str, object]:
        data = dict(zip(self._columns, row))
        for column in self._json_columns:
            data[column] = _json_mapping(data.get(column))
        return data

    def _default_mapping(
        self,
        tenant_id: str,
        provider_policy_id: str = "default",
        collection_id: str = "",
    ) -> dict[str, object]:
        from workers.ingest.provider_policy import ProviderPolicy

        policy = ProviderPolicy(tenant_id=tenant_id, provider_policy_id=provider_policy_id)
        return {
            "provider_policy_id": provider_policy_id,
            "tenant_id": tenant_id,
            "collection_id": collection_id or None,
            "name": "Default provider policy",
            "status": "active",
            "parser_mode": policy.parser_mode,
            "allowed_parser_providers": list(policy.allowed_parser_providers),
            "allowed_ocr_providers": list(policy.allowed_ocr_providers),
            "allowed_layout_providers": list(policy.allowed_layout_providers),
            "allowed_structured_providers": list(policy.allowed_structured_providers),
            "allowed_llm_providers": list(policy.allowed_llm_providers),
            "allowed_embedding_providers": list(policy.allowed_embedding_providers),
            "allowed_visual_embedding_providers": list(policy.allowed_visual_embedding_providers),
            "allowed_vlm_providers": list(policy.allowed_vlm_providers),
            "allowed_caption_providers": list(policy.allowed_caption_providers),
            "allowed_rerank_providers": list(policy.allowed_rerank_providers),
            "allowed_regions": list(policy.allowed_regions),
            "zero_retention_required": policy.zero_retention_required,
            "no_train_required": policy.no_train_required,
            "cross_cloud_processing_allowed": policy.cross_cloud_processing_allowed,
            "customer_opt_in_required": policy.customer_opt_in_required,
            "customer_opt_in_status": policy.customer_opt_in_status,
            "opt_in_status_by_family": dict(policy.opt_in_status_by_family),
            "fallback_policy": dict(policy.fallback_policy),
        }

    def get_mapping(
        self,
        tenant_id: str,
        collection_id: str = "",
        provider_policy_id: str = "default",
    ) -> dict[str, object]:
        _use_tenant(self._conn, tenant_id)
        columns = ", ".join(self._columns)
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    f"SELECT {columns} FROM provider_policies "
                    "WHERE tenant_id = %s AND status = 'active' "
                    "AND (provider_policy_id = %s OR provider_policy_id = 'default') "
                    "AND (collection_id = %s OR collection_id IS NULL OR collection_id = '') "
                    "ORDER BY "
                    "CASE WHEN collection_id = %s THEN 0 ELSE 1 END, "
                    "CASE WHEN provider_policy_id = %s THEN 0 ELSE 1 END, "
                    "updated_at DESC "
                    "LIMIT 1",
                    (
                        tenant_id,
                        provider_policy_id,
                        collection_id,
                        collection_id,
                        provider_policy_id,
                    ),
                )
                row = cur.fetchone()
        except Exception:
            return self._default_mapping(tenant_id, provider_policy_id, collection_id)
        if row is None:
            return self._default_mapping(tenant_id, provider_policy_id, collection_id)
        return self._row_to_mapping(row)

    def list_mappings(self, tenant_id: str, collection_id: str = "") -> list[dict[str, object]]:
        _use_tenant(self._conn, tenant_id)
        columns = ", ".join(self._columns)
        try:
            with self._conn.cursor() as cur:
                if collection_id:
                    cur.execute(
                        f"SELECT {columns} FROM provider_policies "
                        "WHERE tenant_id = %s AND collection_id = %s "
                        "ORDER BY updated_at DESC",
                        (tenant_id, collection_id),
                    )
                else:
                    cur.execute(
                        f"SELECT {columns} FROM provider_policies "
                        "WHERE tenant_id = %s ORDER BY updated_at DESC",
                        (tenant_id,),
                    )
                rows = cur.fetchall()
        except Exception:
            return []
        return [self._row_to_mapping(row) for row in rows]

    def upsert(
        self,
        tenant_id: str,
        provider_policy_id: str,
        body: Mapping[str, object],
    ) -> dict[str, object]:
        _use_tenant(self._conn, tenant_id)
        existing = self.get_mapping(
            tenant_id,
            str(body.get("collection_id") or ""),
            provider_policy_id,
        )
        item = {**existing, **dict(body)}
        item["tenant_id"] = tenant_id
        item["provider_policy_id"] = provider_policy_id

        columns = self._columns
        values = []
        for column in columns:
            value = item.get(column)
            if column in self._json_columns:
                value = Json(dict(value or {}))
            values.append(value)
        placeholders = ", ".join(["%s"] * len(columns))
        assignments = ", ".join(
            f"{column}=EXCLUDED.{column}"
            for column in columns
            if column not in {"provider_policy_id", "tenant_id"}
        )
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO provider_policies ({', '.join(columns)}) "
                f"VALUES ({placeholders}) "
                "ON CONFLICT (provider_policy_id) DO UPDATE SET "
                f"{assignments}, updated_at = now() "
                "WHERE provider_policies.tenant_id = EXCLUDED.tenant_id "
                f"RETURNING {', '.join(columns)}",
                values,
            )
            row = cur.fetchone()
        if row is None:
            raise ValueError("provider_policy_id already belongs to another tenant")
        return self._row_to_mapping(row)

    def get(
        self,
        tenant_id: str,
        collection_id: str = "",
        provider_policy_id: str = "default",
    ):
        from workers.ingest.provider_policy import ProviderPolicy

        return ProviderPolicy.from_mapping(
            self.get_mapping(tenant_id, collection_id, provider_policy_id)
        )


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

        run_id = _stable_id("ing", message.tenant_id, message.idempotency_key)
        state_id = _stable_id("dps", message.tenant_id, message.document_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_runs (ingestion_run_id, tenant_id, collection_id, source_id, "
                "document_id, idempotency_key, document_ref, content_type, type, trigger, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued') "
                "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING "
                "RETURNING ingestion_run_id",
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
            inserted = cur.fetchone()
            if inserted is None:
                existing = self.get_by_idempotency_key(message.tenant_id, message.idempotency_key)
                assert existing is not None
                return existing, False
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
                "retry_count, chunk_count, failure_reason, dagster_run_id, async_provider, "
                "async_job_id, async_job_status, started_at, finished_at, "
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
                "retry_count, chunk_count, failure_reason, dagster_run_id, async_provider, "
                "async_job_id, async_job_status, started_at, finished_at, "
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
                "retry_count, chunk_count, failure_reason, dagster_run_id, async_provider, "
                "async_job_id, async_job_status, started_at, finished_at, "
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

    def list_processing_states(
        self, tenant_id: str, *, collection_id: str = "", source_id: str = ""
    ) -> list[DocumentProcessingState]:
        _use_tenant(self._conn, tenant_id)
        clauses: list[str] = []
        params: list[object] = []
        if collection_id:
            clauses.append("collection_id = %s")
            params.append(collection_id)
        if source_id:
            clauses.append("source_id = %s")
            params.append(source_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, document_id, ingestion_run_id, collection_id, source_id, status, "
                "content_checksum, parser_version, chunking_config_version, embedding_model_version, "
                "chunk_count, failure_reason, updated_at "
                "FROM document_processing_states" + where + " ORDER BY updated_at DESC",
                params,
            )
            return [_row_to_processing_state(row) for row in cur.fetchall()]

    def list_source_document_manifests(
        self, tenant_id: str, source_id: str
    ) -> tuple[SourceDocumentManifest, ...]:
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, collection_id, source_id, source_document_id, document_id, "
                "content_checksum, metadata, status, created_at, updated_at "
                "FROM source_document_manifests WHERE source_id = %s ORDER BY updated_at DESC",
                (source_id,),
            )
            rows = cur.fetchall()
        return tuple(
            SourceDocumentManifest(
                tenant_id=row[0],
                collection_id=row[1],
                source_id=row[2],
                source_document_id=row[3],
                document_id=row[4],
                content_checksum=row[5] or "",
                metadata=_load_jsonish(row[6]) or {},
                deleted_in_source=row[7] == "deleted",
                observed_at=_iso(row[9] or row[8]),
            )
            for row in rows
        )

    def list_asset_materializations(
        self, tenant_id: str, *, source_id: str = "", sync_run_id: str = ""
    ) -> tuple[AssetMaterializationRef, ...]:
        _use_tenant(self._conn, tenant_id)
        clauses: list[str] = []
        params: list[object] = []
        if source_id:
            clauses.append("source_id = %s")
            params.append(source_id)
        if sync_run_id:
            clauses.append("sync_run_id = %s")
            params.append(sync_run_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, collection_id, source_id, sync_run_id, dagster_asset_key, "
                "partition_key, asset_materialization_id, document_id, chunk_ids, storage_uri, "
                "dagster_run_id, created_at FROM asset_materialization_refs"
                + where
                + " ORDER BY created_at DESC",
                params,
            )
            rows = cur.fetchall()
        return tuple(
            AssetMaterializationRef(
                tenant_id=row[0],
                collection_id=row[1],
                source_id=row[2],
                sync_run_id=row[3],
                dagster_asset_key=row[4],
                partition_key=row[5],
                asset_materialization_id=row[6],
                document_id=row[7] or "",
                chunk_ids=tuple(row[8] or ()),
                storage_uri=row[9] or "",
                dagster_run_id=row[10] or "",
                created_at=_iso(row[11]),
            )
            for row in rows
        )

    def source_sync_status(
        self,
        tenant_id: str,
        source_id: str,
        *,
        dagster_base_url: str = "",
    ) -> SourceSyncStatusProjection | None:
        state = self.source_sync_state(tenant_id, source_id)
        if state is None:
            return None
        runs = self.list_runs(tenant_id, source_id=source_id)
        latest_run = runs[0] if runs else None
        manifests = self.list_source_document_manifests(tenant_id, source_id)
        if manifests:
            documents = tuple(
                self._project_manifest_document(manifest, latest_run) for manifest in manifests
            )
        else:
            documents = tuple(
                self._project_processing_state(state)
                for state in self.list_processing_states(tenant_id, source_id=source_id)
                if state.document_id != f"{source_id}::__source_sync__"
            )
        dagster_run_id = latest_run.dagster_run_id if latest_run else ""
        return SourceSyncStatusProjection(
            tenant_id=state.tenant_id,
            source_id=state.source_id,
            collection_id=state.collection_id,
            status=state.status,
            last_manifest_checksum=state.last_manifest_checksum,
            summary={
                "observed_count": state.observed_count,
                "changed_count": state.changed_count,
                "deleted_count": state.deleted_count,
                "skipped_count": state.skipped_count,
                "failed_count": state.failed_count,
            },
            documents=documents,
            asset_materializations=self.list_asset_materializations(tenant_id, source_id=source_id),
            dagster_run_id=dagster_run_id,
            dagster_run_url=(
                dagster_run_url(dagster_base_url, dagster_run_id)
                if dagster_base_url and dagster_run_id
                else ""
            ),
            correlation_id=state.last_ingestion_run_id,
        )

    def _project_manifest_document(
        self, manifest: SourceDocumentManifest, latest_run: IngestionRun | None
    ) -> DocumentProcessingProjection:
        state = self.processing_state(manifest.tenant_id, manifest.target_document_id)
        dagster_run_id = latest_run.dagster_run_id if latest_run else ""
        if state is None:
            return DocumentProcessingProjection(
                document_id=manifest.target_document_id,
                source_document_id=manifest.source_document_id,
                content_checksum=manifest.content_checksum,
                parser_version=manifest.parser_version,
                chunking_config_version=manifest.chunking_config_version,
                embedding_model_version=manifest.embedding_model_version,
                parse_status="pending",
                chunk_status="pending",
                embedding_status="pending",
                index_status="pending",
                dagster_run_id=dagster_run_id,
            )
        return self._project_processing_state(state, source_document_id=manifest.source_document_id)

    def _project_processing_state(
        self,
        state: DocumentProcessingState,
        *,
        source_document_id: str = "",
    ) -> DocumentProcessingProjection:
        return DocumentProcessingProjection(
            document_id=state.document_id,
            source_document_id=source_document_id or state.document_id,
            content_checksum=state.content_checksum,
            parser_version=state.parser_version,
            chunking_config_version=state.chunking_config_version,
            embedding_model_version=state.embedding_model_version,
            parse_status=state.status,
            chunk_status=state.status,
            embedding_status=state.status,
            index_status=state.status,
            last_indexed_at=state.updated_at if state.status == "succeeded" else "",
            last_error=state.failure_reason,
        )

    def upsert_source_sync_state(self, state: SourceSyncState) -> SourceSyncState:
        _use_tenant(self._conn, state.tenant_id)
        _ensure_collection_parent(self._conn, state.tenant_id, state.collection_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO source_sync_states "
                "(source_id, tenant_id, collection_id, status, last_manifest_checksum, "
                "last_ingestion_run_id, observed_count, changed_count, deleted_count, skipped_count, "
                "failed_count, last_synced_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NULLIF(%s, '' )::timestamptz) "
                "ON CONFLICT ON CONSTRAINT source_sync_states_pkey DO UPDATE SET "
                "collection_id=EXCLUDED.collection_id, status=EXCLUDED.status, "
                "last_manifest_checksum=EXCLUDED.last_manifest_checksum, "
                "last_ingestion_run_id=EXCLUDED.last_ingestion_run_id, "
                "observed_count=EXCLUDED.observed_count, changed_count=EXCLUDED.changed_count, "
                "deleted_count=EXCLUDED.deleted_count, skipped_count=EXCLUDED.skipped_count, "
                "failed_count=EXCLUDED.failed_count, last_synced_at=EXCLUDED.last_synced_at, "
                "updated_at=now()",
                (
                    state.source_id,
                    state.tenant_id,
                    state.collection_id,
                    state.status,
                    state.last_manifest_checksum,
                    state.last_ingestion_run_id,
                    state.observed_count,
                    state.changed_count,
                    state.deleted_count,
                    state.skipped_count,
                    state.failed_count,
                    state.last_synced_at,
                ),
            )
        refreshed = self.source_sync_state(state.tenant_id, state.source_id)
        return refreshed or state

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
                "retry_count, chunk_count, failure_reason, dagster_run_id, async_provider, "
                "async_job_id, async_job_status, started_at, finished_at, "
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

    def mark_queued(self, run: IngestionRun) -> None:
        self._mark(run, "queued")
        _use_tenant(self._conn, run.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_runs SET sqs_message_id = '', finished_at = NULL, "
                "failure_reason = '', updated_at = now() WHERE ingestion_run_id = %s",
                (run.ingestion_run_id,),
            )
        run.sqs_message_id = ""
        run.failure_reason = ""
        run.finished_at = ""

    def mark_async_job(self, run: IngestionRun, *, provider: str, job_id: str, status: str) -> None:
        _use_tenant(self._conn, run.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_runs SET async_provider = %s, async_job_id = %s, "
                "async_job_status = %s, updated_at = now() WHERE ingestion_run_id = %s",
                (provider, job_id, status, run.ingestion_run_id),
            )
        run.async_provider = provider
        run.async_job_id = job_id
        run.async_job_status = status

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

    def mark_partially_succeeded(
        self,
        run: IngestionRun,
        *,
        reason: str,
        chunk_count: int,
        content_checksum: str = "",
        parser_version: str = "",
        chunking_config_version: str = "",
        embedding_model_version: str = "",
    ) -> None:
        self._mark(
            run,
            "partially_succeeded",
            chunk_count=chunk_count,
            reason=reason,
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
