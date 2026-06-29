"""Production source-sync orchestration.

This service keeps datasource sync out of the HTTP handler: the API records a parent ingestion run and
queues a ``source_sync`` message; workers resolve credentials, enumerate source documents, and feed the
existing document ingestion path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from raku_rag.domain.models import JobStatus
from raku_rag.interfaces.base import Connector
from raku_rag.persistence.datasources import (
    DataSourceRepository,
    materialize_datasource_credentials,
)
from raku_rag.persistence.secret_store import SecretStore
from raku_rag.services.datasource_onboarding import build_datasource_preview
from raku_rag.services.datasource_sync import SyncDocument, build_sync_documents
from raku_rag.workers.ingestion import (
    IngestionJobMessage,
    IngestionRun,
    IngestionRunStore,
    SourceSyncJobMessage,
    SourceSyncState,
    _now,
)


@dataclass
class SourceSyncService:
    system: object
    runs: IngestionRunStore
    datasource_repo: DataSourceRepository
    secret_store: SecretStore
    child_queue: object | None = None
    connector: Connector | None = None
    oauth_connections: object | None = None
    oauth_secret_store: SecretStore | None = None

    def request_source_sync(
        self,
        *,
        tenant_id: str,
        source_id: str,
        body: Mapping[str, object] | None = None,
        requested_by: str = "",
    ) -> tuple[dict, SourceSyncJobMessage, bool]:
        body = dict(body or {})
        datasource = self.datasource_repo.get(tenant_id, source_id)
        if datasource is None:
            raise KeyError("datasource not found")
        collection_id = str(
            body.get("collection_id") or datasource.get("collection_id") or "default"
        )
        idempotency_key = str(body.get("idempotency_key") or "")
        if not idempotency_key:
            idempotency_key = "source-sync:" + _digest(
                [tenant_id, source_id, collection_id, body, _now()]
            )
        parent = _parent_message(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            idempotency_key=idempotency_key,
        )
        run, created = self.runs.create_queued(parent, trigger="api", run_type="manual_sync")
        self.runs.upsert_source_sync_state(
            SourceSyncState(
                tenant_id=tenant_id,
                source_id=source_id,
                collection_id=collection_id,
                status="queued",
                last_ingestion_run_id=run.ingestion_run_id,
            )
        )
        message = SourceSyncJobMessage(
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            sync_run_id=run.ingestion_run_id,
            scope=body,
            requested_by=requested_by,
            force=bool(body.get("force")),
        )
        return (
            _sync_response(
                source_id=source_id,
                collection_id=collection_id,
                status=run.status,
                run_id=run.ingestion_run_id,
                observed_count=0,
                changed_count=0,
                failed_count=0,
                runs=[],
            ),
            message,
            created,
        )

    def test_connection(
        self, *, tenant_id: str, source_id: str, body: Mapping[str, object] | None = None
    ) -> dict:
        datasource = self.datasource_repo.get(tenant_id, source_id)
        if datasource is None:
            raise KeyError("datasource not found")
        materialized = materialize_datasource_credentials(datasource, self.secret_store)
        documents = build_sync_documents(source_id, materialized, body=body or {}, limit=1)
        return {"ok": True, "source_id": source_id, "sample_count": len(documents)}

    def preview_source(
        self, *, tenant_id: str, source_id: str, body: Mapping[str, object] | None = None
    ) -> dict:
        """Sample a datasource and explain canonical mapping before indexing anything."""

        body = dict(body or {})
        datasource = self.datasource_repo.get(tenant_id, source_id)
        if datasource is None:
            raise KeyError("datasource not found")
        materialized = materialize_datasource_credentials(datasource, self.secret_store)
        limit = _preview_document_limit(body)
        documents = build_sync_documents(source_id, materialized, body=body, limit=limit)
        return build_datasource_preview(
            source_id=source_id,
            datasource=materialized,
            documents=documents,
            body=body,
        )

    def execute_source_sync(self, message: SourceSyncJobMessage) -> dict:
        parent = _parent_message(
            tenant_id=message.tenant_id,
            collection_id=message.collection_id,
            source_id=message.source_id,
            idempotency_key=message.idempotency_key,
        )
        run, _ = self.runs.create_queued(parent, trigger="sqs", run_type="manual_sync")
        if run.status == JobStatus.SUCCEEDED.value and not message.force:
            return _sync_response(
                source_id=message.source_id,
                collection_id=message.collection_id,
                status=run.status,
                run_id=run.ingestion_run_id,
                observed_count=0,
                changed_count=0,
                failed_count=0,
                runs=[],
            )

        self.runs.mark_running(run)
        self.runs.upsert_source_sync_state(
            SourceSyncState(
                tenant_id=message.tenant_id,
                source_id=message.source_id,
                collection_id=message.collection_id,
                status="syncing",
                last_ingestion_run_id=run.ingestion_run_id,
            )
        )
        try:
            datasource = self.datasource_repo.get(message.tenant_id, message.source_id)
            if datasource is None:
                raise KeyError("datasource not found")
            materialized = materialize_datasource_credentials(datasource, self.secret_store)
            sync_scope = dict(message.scope)
            self._inject_google_drive_access_token(message, materialized, sync_scope)
            documents = build_sync_documents(message.source_id, materialized, body=sync_scope)
            if not documents:
                raise ValueError("datasource did not produce any documents")

            child_runs: list[dict] = []
            for document in documents:
                child = self._ingest_document(message, datasource, document)
                child_runs.append(_ingest_response_json(child))

            failed_or_dead = [
                item
                for item in child_runs
                if item.get("status") in {JobStatus.FAILED.value, JobStatus.DEAD_LETTER.value}
            ]
            in_progress = [
                item
                for item in child_runs
                if item.get("status") in {JobStatus.QUEUED.value, JobStatus.RUNNING.value}
            ]
            if in_progress:
                final_status = "syncing"
                chunk_count = sum(int(item.get("chunk_count") or 0) for item in child_runs)
                # Keep the parent run open while child ingestion jobs finish. The worker refreshes this
                # state as child runs complete, so source-sync never looks successful while PDFs are
                # still queued/running.
                self.runs.mark_running(run)
            elif len(failed_or_dead) == len(child_runs):
                final_status = JobStatus.FAILED.value
                self.runs.mark_failed(run, reason="all synced documents failed", retry_count=0)
            else:
                final_status = (
                    "partially_succeeded" if failed_or_dead else JobStatus.SUCCEEDED.value
                )
                chunk_count = sum(int(item.get("chunk_count") or 0) for item in child_runs)
                if failed_or_dead:
                    self.runs.mark_partially_succeeded(
                        run,
                        reason=f"{len(failed_or_dead)} synced document(s) failed",
                        chunk_count=chunk_count,
                        content_checksum=_manifest_checksum(documents),
                    )
                else:
                    self.runs.mark_succeeded(
                        run,
                        chunk_count=chunk_count,
                        content_checksum=_manifest_checksum(documents),
                    )

            self.runs.upsert_source_sync_state(
                SourceSyncState(
                    tenant_id=message.tenant_id,
                    source_id=message.source_id,
                    collection_id=message.collection_id,
                    status=final_status,
                    last_manifest_checksum=_manifest_checksum(documents),
                    last_ingestion_run_id=run.ingestion_run_id,
                    observed_count=len(documents),
                    changed_count=len(child_runs) - len(failed_or_dead) - len(in_progress),
                    failed_count=len(failed_or_dead),
                    last_synced_at=_now() if final_status == JobStatus.SUCCEEDED.value else "",
                )
            )
            return _sync_response(
                source_id=message.source_id,
                collection_id=message.collection_id,
                status=final_status,
                run_id=run.ingestion_run_id,
                observed_count=len(documents),
                changed_count=len(child_runs) - len(failed_or_dead) - len(in_progress),
                failed_count=len(failed_or_dead),
                runs=child_runs,
                datasource=datasource,
            )
        except Exception as exc:
            self.runs.mark_failed(run, reason=str(exc), retry_count=0)
            self.runs.upsert_source_sync_state(
                SourceSyncState(
                    tenant_id=message.tenant_id,
                    source_id=message.source_id,
                    collection_id=message.collection_id,
                    status=JobStatus.FAILED.value,
                    last_ingestion_run_id=run.ingestion_run_id,
                    failed_count=1,
                )
            )
            raise

    def _inject_google_drive_access_token(
        self,
        message: SourceSyncJobMessage,
        datasource: Mapping[str, object],
        scope: dict,
    ) -> None:
        config = datasource.get("config") if isinstance(datasource.get("config"), Mapping) else {}
        source_type = str(dict(config).get("source_type") or datasource.get("type") or "").lower()
        if source_type != "google_drive":
            return
        if self.oauth_connections is None:
            raise ValueError("google_drive datasource is not connected (reconnect required)")
        conn_id = str(dict(config).get("connection_id") or "")
        connection = (
            self.oauth_connections.get(message.tenant_id, conn_id)
            if conn_id
            else self.oauth_connections.get_by_source(message.tenant_id, message.source_id)
        )
        if connection is None:
            raise ValueError("google_drive datasource is not connected (reconnect required)")
        from raku_rag.services import oauth_token_resolver

        scope["fresh_access_token"] = oauth_token_resolver.resolve_fresh_access_token(
            connection,
            self.oauth_secret_store or self.secret_store,
        )

    def _ingest_document(
        self,
        message: SourceSyncJobMessage,
        datasource: Mapping[str, object],
        document: SyncDocument,
    ) -> IngestionRun:
        mfg_meta = _mfg_metadata_for_sync(
            message.scope, datasource, message.tenant_id, document.document_id
        )
        document_ref = _stage_child_document_ref(
            self.connector,
            tenant_id=message.tenant_id,
            collection_id=message.collection_id,
            source_id=message.source_id,
            document_id=document.document_id,
            document_ref=document.document_ref,
            raw=document.raw,
            content_type=document.content_type,
        )
        ingest_document = getattr(self.system, "ingest_document", None)
        if callable(ingest_document):
            child = ingest_document(
                tenant_id=message.tenant_id,
                collection_id=message.collection_id,
                source_id=message.source_id,
                document_id=document.document_id,
                document_ref=document_ref,
                raw=document.raw,
                content_type=document.content_type,
                manufacturing_metadata=mfg_meta,
            )
            self._enqueue_child_if_needed(child)
            return child

        checksum = hashlib.sha256(document.raw).hexdigest()
        child_message = IngestionJobMessage(
            idempotency_key=(
                f"source-sync:{message.collection_id}:{message.source_id}:"
                f"{document.document_id}:{checksum}"
            ),
            tenant_id=message.tenant_id,
            collection_id=message.collection_id,
            source_id=message.source_id,
            document_id=document.document_id,
            document_ref=document_ref,
            content_type=document.content_type,
        )
        child_run, created = self.runs.create_queued(child_message, trigger="sqs")
        if not created and child_run.status == JobStatus.SUCCEEDED.value:
            return child_run
        self.runs.mark_running(child_run)
        job = self.system.ingestion.ingest(
            tenant_id=message.tenant_id,
            collection_id=message.collection_id,
            source_id=message.source_id,
            document_id=document.document_id,
            raw=document.raw,
            content_type=document.content_type,
            chunking_metadata=mfg_meta.to_mapping() if mfg_meta is not None else None,
        )
        if job.status == JobStatus.SUCCEEDED.value:
            self.runs.mark_succeeded(child_run, chunk_count=job.chunk_count)
        else:
            self.runs.mark_failed(
                child_run, reason=job.failure_reason or "ingestion failed", retry_count=0
            )
        return child_run

    def _enqueue_child_if_needed(self, child: IngestionRun) -> None:
        if self.child_queue is None:
            return
        if child.status != JobStatus.QUEUED.value or child.sqs_message_id:
            return
        enqueue = getattr(self.child_queue, "enqueue_message", None)
        if not callable(enqueue):
            return
        message = IngestionJobMessage(
            idempotency_key=child.idempotency_key,
            tenant_id=child.tenant_id,
            collection_id=child.collection_id,
            source_id=child.source_id,
            document_id=child.document_id,
            document_ref=child.document_ref,
            content_type=child.content_type,
        )
        message_id = str(enqueue(message.to_dict()))
        self.runs.mark_message_id(child, message_id)


def _parent_message(
    *, tenant_id: str, collection_id: str, source_id: str, idempotency_key: str
) -> IngestionJobMessage:
    return IngestionJobMessage(
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_id=source_id,
        document_id=f"{source_id}::__source_sync__",
        document_ref=f"datasource://{source_id}",
        content_type="application/x-raku-source-sync",
    )


def _sync_response(
    *,
    source_id: str,
    collection_id: str,
    status: str,
    run_id: str,
    observed_count: int,
    changed_count: int,
    failed_count: int,
    runs: list[dict],
    datasource: Mapping[str, object] | None = None,
) -> dict:
    payload = {
        "source_id": source_id,
        "collection_id": collection_id,
        "status": status,
        "sync_run_id": run_id,
        "ingestion_run_id": run_id,
        "status_url": f"/v1/admin/ingestion-runs/{run_id}",
        "observed_count": observed_count,
        "changed_count": changed_count,
        "failed_count": failed_count,
        "runs": runs,
    }
    if datasource is not None:
        payload["approval_policy"] = _datasource_approval_policy(datasource)
        payload["applied_approval_status"] = _approval_from_datasource_policy(datasource)[0]
    return payload


def _ingest_response_json(run: IngestionRun) -> dict:
    return {
        "ingestion_run_id": run.ingestion_run_id,
        "document_id": run.document_id,
        "status": run.status,
        "status_url": f"/v1/admin/ingestion-runs/{run.ingestion_run_id}",
        "failure_reason": run.failure_reason,
        "chunk_count": run.chunk_count,
        "sqs_message_id": run.sqs_message_id,
    }


def _stage_child_document_ref(
    connector: Connector | None,
    *,
    tenant_id: str,
    collection_id: str,
    source_id: str,
    document_id: str,
    document_ref: str,
    raw: bytes,
    content_type: str,
) -> str:
    if not _is_visual_content_type(content_type) or document_ref.startswith("s3://"):
        return document_ref
    put_bytes = getattr(connector, "put_bytes", None) if connector is not None else None
    if not callable(put_bytes):
        return document_ref
    checksum = hashlib.sha256(raw).hexdigest()
    key = "/".join(
        [
            "source-sync",
            _safe_key_part(tenant_id),
            _safe_key_part(collection_id),
            _safe_key_part(source_id),
            _safe_key_part(document_id),
            f"{checksum}{_extension_for_content_type(content_type)}",
        ]
    )
    return str(put_bytes(key, raw, content_type=content_type))


def _is_visual_content_type(content_type: str) -> bool:
    normalized = content_type.lower().split(";", 1)[0].strip()
    return normalized == "application/pdf" or normalized.startswith("image/")


def _extension_for_content_type(content_type: str) -> str:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized == "application/pdf":
        return ".pdf"
    if normalized in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if normalized == "image/png":
        return ".png"
    return ".bin"


def _safe_key_part(value: object) -> str:
    text = str(value or "")
    return "".join(ch if ch.isalnum() or ch in "._=-" else "-" for ch in text).strip("-")


def _manifest_checksum(documents: list[SyncDocument]) -> str:
    digest = hashlib.sha256()
    for document in documents:
        digest.update(document.document_id.encode("utf-8"))
        digest.update(hashlib.sha256(document.raw).hexdigest().encode("ascii"))
    return digest.hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _preview_document_limit(body: Mapping[str, object]) -> int:
    raw = body.get("limit") or body.get("sample_documents") or body.get("max_documents") or 3
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = 3
    return max(1, min(limit, 10))


def _mfg_raw_from_body(body: Mapping[str, object]) -> dict | None:
    raw = body.get("manufacturing")
    if raw is None:
        meta_block = body.get("manufacturing_metadata") or {}
        approval_block = body.get("approval") or {}
        if not meta_block and not approval_block:
            return None
        raw = {**dict(meta_block), **dict(approval_block)}
        if "document_type" in raw and "document_kind" not in raw:
            raw["document_kind"] = raw.pop("document_type")
    return dict(raw) if isinstance(raw, Mapping) else None


def _datasource_approval_policy(datasource: Mapping[str, object]) -> str:
    config = datasource.get("config") if isinstance(datasource.get("config"), Mapping) else {}
    policy = str(dict(config).get("approval_policy") or "review_required").strip().lower()
    return "trusted" if policy == "trusted" else "review_required"


def _approval_from_datasource_policy(
    datasource: Mapping[str, object],
) -> tuple[str, str, str | None]:
    if _datasource_approval_policy(datasource) == "trusted":
        config = datasource.get("config") if isinstance(datasource.get("config"), Mapping) else {}
        eff = dict(config).get("approval_effective_date") or _now()[:10]
        return ("approved", "imported", str(eff))
    return ("pending_review", "workflow", None)


def _datasource_mapping_profile_extra(datasource: Mapping[str, object]) -> dict:
    config = datasource.get("config") if isinstance(datasource.get("config"), Mapping) else {}
    profile = dict(config).get("mapping_profile")
    if not isinstance(profile, Mapping):
        return {}
    extra: dict[str, object] = {}
    profile_type = profile.get("profile_type") or profile.get("data_profile")
    if profile_type:
        extra["datasource_profile_type"] = str(profile_type)
    raw_required = profile.get("required_fields")
    if isinstance(raw_required, (list, tuple)):
        extra["datasource_required_fields"] = [str(field) for field in raw_required]
    raw_mapping = {}
    if isinstance(profile.get("mapping"), Mapping):
        raw_mapping.update(profile.get("mapping") or {})
    if isinstance(profile.get("field_mapping"), Mapping):
        raw_mapping.update(profile.get("field_mapping") or {})
    if raw_mapping:
        extra["datasource_mapped_fields"] = sorted({str(value) for value in raw_mapping.values()})
    return extra


def _mfg_metadata_for_sync(
    body: Mapping[str, object], datasource: Mapping[str, object], tenant_id: str, document_id: str
):
    from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata

    raw = dict(_mfg_raw_from_body(body) or {})
    status, source, eff = _approval_from_datasource_policy(datasource)
    raw["approval_status"] = status
    raw["approval_source"] = source
    raw["effective_date"] = eff
    extra = dict(raw.get("extra") or {}) if isinstance(raw.get("extra"), Mapping) else {}
    extra.update(_datasource_mapping_profile_extra(datasource))
    if extra:
        raw["extra"] = extra
    return ManufacturingDocumentMetadata.from_mapping(
        {**raw, "tenant_id": tenant_id, "document_id": document_id}
    )
