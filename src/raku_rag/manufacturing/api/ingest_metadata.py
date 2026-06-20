"""Manufacturing ingestion metadata and sync/status API helpers."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib

from raku_rag.domain.models import IdentityClaims, JobStatus
from raku_rag.persistence.control_plane import InMemoryControlPlaneStateRepository
from raku_rag.workers.ingestion import IngestionJobMessage, IngestionRun, SourceSyncState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ManufacturingSyncStatusService:
    """Manufacturing façade over the 001 ingestion control-plane state."""

    def __init__(
        self,
        repository: InMemoryControlPlaneStateRepository | None = None,
        *,
        dagster_base_url: str = "",
    ) -> None:
        self.repository = repository or InMemoryControlPlaneStateRepository()
        self.dagster_base_url = dagster_base_url

    def request_sync(
        self,
        principal: IdentityClaims,
        source_id: str,
        *,
        collection_id: str = "manufacturing",
        document_id: str = "",
        document_ref: str = "",
        content_type: str = "text/plain",
        idempotency_key: str = "",
    ) -> dict:
        """POST /v1/manufacturing/sources/{source_id}/sync."""

        effective_document_id = document_id or f"{source_id}:manual-sync"
        key = idempotency_key or _idempotency_key(
            principal.tenant_id,
            source_id,
            effective_document_id,
            document_ref,
        )
        message = IngestionJobMessage(
            idempotency_key=key,
            tenant_id=principal.tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=effective_document_id,
            document_ref=document_ref or f"manufacturing://{source_id}/{effective_document_id}",
            content_type=content_type,
        )
        run, _created = self.repository.create_ingestion_run(
            message,
            trigger="manual",
            run_type="manufacturing_sync",
        )
        self.repository.upsert_source_sync_state(
            SourceSyncState(
                tenant_id=principal.tenant_id,
                source_id=source_id,
                collection_id=collection_id,
                status="queued",
                last_ingestion_run_id=run.ingestion_run_id,
                observed_count=1,
                changed_count=1,
                last_synced_at="",
                created_at=run.created_at,
                updated_at=_now(),
            )
        )
        return {
            "ingestion_run_id": run.ingestion_run_id,
            "status": run.status,
            "status_url": f"/v1/manufacturing/ingestion-runs/{run.ingestion_run_id}",
        }

    def sync_status(
        self,
        principal: IdentityClaims,
        source_id: str,
    ) -> dict:
        """GET /v1/manufacturing/sources/{source_id}/sync-status."""

        projection = self.repository.source_sync_status(
            principal.tenant_id,
            source_id,
            dagster_base_url=self.dagster_base_url,
        )
        if projection is None:
            return {
                "tenant_id": principal.tenant_id,
                "source_id": source_id,
                "status": "not_found",
                "summary": {},
                "documents": [],
                "asset_materializations": [],
            }
        payload = projection.to_dict()
        payload["manufacturing_metadata"] = {
            "approval_metadata_checksum_observed": True,
            "metadata_only_updates_supported": True,
            "dagster_run_fields_internal_only": True,
        }
        return _sanitize_operator_fields(payload, principal)

    def ingestion_run(
        self,
        principal: IdentityClaims,
        ingestion_run_id: str,
    ) -> dict:
        """GET /v1/manufacturing/ingestion-runs/{ingestion_run_id}."""

        run = self.repository.get_ingestion_run(principal.tenant_id, ingestion_run_id)
        if run is None:
            return {
                "tenant_id": principal.tenant_id,
                "ingestion_run_id": ingestion_run_id,
                "status": "not_found",
                "documents": [],
            }
        states = self.repository.list_processing_states(
            principal.tenant_id,
            collection_id=run.collection_id,
            source_id=run.source_id,
        )
        payload = {
            **_run_to_dict(run),
            "status_url": f"/v1/manufacturing/ingestion-runs/{run.ingestion_run_id}",
            "documents": [asdict(state) for state in states],
            "summary": {
                "document_count": len(states),
                "succeeded_count": sum(
                    1 for state in states if state.status == JobStatus.SUCCEEDED.value
                ),
                "failed_count": sum(
                    1
                    for state in states
                    if state.status in {JobStatus.FAILED.value, JobStatus.DEAD_LETTER.value}
                ),
            },
        }
        return _sanitize_operator_fields(payload, principal)


def _run_to_dict(run: IngestionRun) -> dict:
    return {
        "ingestion_run_id": run.ingestion_run_id,
        "tenant_id": run.tenant_id,
        "collection_id": run.collection_id,
        "source_id": run.source_id,
        "document_id": run.document_id,
        "type": run.type,
        "trigger": run.trigger,
        "status": run.status,
        "failure_reason": run.failure_reason,
        "chunk_count": run.chunk_count,
        "retry_count": run.retry_count,
        "dagster_run_id": run.dagster_run_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _sanitize_operator_fields(payload: dict, principal: IdentityClaims) -> dict:
    if _is_internal_operator(principal):
        return payload
    cleaned = dict(payload)
    cleaned.pop("dagster_run_id", None)
    cleaned.pop("dagster_run_url", None)
    if "documents" in cleaned:
        cleaned["documents"] = [
            _sanitize_operator_fields(dict(item), principal) for item in cleaned["documents"]
        ]
    if "asset_materializations" in cleaned:
        cleaned["asset_materializations"] = [
            _strip_keys(dict(item), {"dagster_run_id", "dagster_run_url"})
            for item in cleaned["asset_materializations"]
        ]
    return cleaned


def _strip_keys(payload: dict, keys: set[str]) -> dict:
    for key in keys:
        payload.pop(key, None)
    return payload


def _is_internal_operator(principal: IdentityClaims) -> bool:
    roles = set(principal.roles)
    return bool(roles & {"internal_operator", "platform_operator", "admin"})


def _idempotency_key(
    tenant_id: str,
    source_id: str,
    document_id: str,
    document_ref: str,
) -> str:
    raw = f"{tenant_id}:{source_id}:{document_id}:{document_ref}".encode("utf-8")
    return "mfg_sync_" + hashlib.sha256(raw).hexdigest()[:16]


__all__ = ["ManufacturingSyncStatusService"]
