"""T062a - failed ingestion retry orchestration helpers."""

from __future__ import annotations

from dataclasses import dataclass

from raku_rag.domain.models import JobStatus
from raku_rag.workers.ingestion import DocumentProcessingState, IngestionRun, IngestionRunStore

RETRYABLE_STATUSES = (JobStatus.FAILED.value, JobStatus.DEAD_LETTER.value)


@dataclass(frozen=True)
class FailedIngestionRetryCandidate:
    tenant_id: str
    ingestion_run_id: str
    document_id: str
    source_id: str
    document_ref: str
    content_type: str
    postgres_status: str
    processing_state_status: str
    failure_reason: str
    retry_count: int
    dagster_run_id: str

    @property
    def retryable(self) -> bool:
        return bool(self.document_ref) and self.postgres_status in RETRYABLE_STATUSES

    @property
    def status_reconciled(self) -> bool:
        return self.processing_state_status == self.postgres_status


def candidate_from_run(
    run: IngestionRun,
    state: DocumentProcessingState | None,
) -> FailedIngestionRetryCandidate:
    return FailedIngestionRetryCandidate(
        tenant_id=run.tenant_id,
        ingestion_run_id=run.ingestion_run_id,
        document_id=run.document_id,
        source_id=run.source_id,
        document_ref=run.document_ref,
        content_type=run.content_type,
        postgres_status=run.status,
        processing_state_status=state.status if state else "",
        failure_reason=run.failure_reason or (state.failure_reason if state else ""),
        retry_count=run.retry_count,
        dagster_run_id=run.dagster_run_id,
    )


def discover_failed_retry_candidates(
    store: IngestionRunStore,
    tenant_id: str,
    *,
    source_id: str = "",
    limit: int = 50,
) -> tuple[FailedIngestionRetryCandidate, ...]:
    candidates: list[FailedIngestionRetryCandidate] = []
    for status in RETRYABLE_STATUSES:
        for run in store.list_runs(tenant_id, status=status, source_id=source_id, limit=limit):
            state = store.processing_state(tenant_id, run.document_id)
            candidate = candidate_from_run(run, state)
            if candidate.retryable:
                candidates.append(candidate)
    return tuple(sorted(candidates, key=lambda item: item.ingestion_run_id))
