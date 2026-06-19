"""T037 — POST /v1/manufacturing/trouble-cases/search service (US3; contracts §C, FR-MFG-008/009/021).

Orchestrates the reused ``TroubleCaseRetriever`` (knowledge/trouble_cases.py) behind the in-memory
``ManufacturingSystem`` entrypoint, mirroring contracts/mfg-openapi.md §C as a Python method (not HTTP).

It adds NO authz / retrieval mechanism: visibility is the 001 ACL pre-filter (reached via the reused
``RetrievalService`` inside the retriever), and the candidate/past-example display normalization is the
retriever's (Hard Rule 4). This layer assigns a correlation id, builds the response envelope, and
audits answer-generation + citation-access by REFERENCE ID only (FR-MFG-021 / SC-MFG-010).

stdlib only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from raku_rag.core.errors import AnswerStatus
from raku_rag.domain.models import IdentityClaims, QueryProfile
from raku_rag.manufacturing.domain.audit import AuditLogEntry, InMemoryAuditLogWriter
from raku_rag.manufacturing.knowledge.trouble_cases import (
    TroubleCaseRetriever,
    TroubleCaseSearchResponse,
)
from raku_rag.observability.logging import new_correlation_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TroubleCaseSearchService:
    """In-memory trouble-case search orchestration + audit (US3)."""

    def __init__(
        self,
        *,
        retriever: TroubleCaseRetriever,
        audit: InMemoryAuditLogWriter,
    ) -> None:
        self._retriever = retriever
        self._audit = audit

    def search(
        self,
        principal: IdentityClaims,
        symptom_query: str,
        profile: QueryProfile,
        *,
        manufacturing_filters: dict | None = None,
    ) -> TroubleCaseSearchResponse:
        correlation_id = new_correlation_id()
        matches, accessed_doc_ids = self._retriever.find_similar(
            principal,
            symptom_query,
            profile,
            manufacturing_filters=manufacturing_filters,
        )
        status = (
            AnswerStatus.OK.value if matches else AnswerStatus.INSUFFICIENT_EVIDENCE.value
        )
        resp = TroubleCaseSearchResponse(
            status=status, results=matches, correlation_id=correlation_id
        )

        # FR-MFG-021 — audit the trouble-case search decision + citation access (reference IDs only).
        citation_ids = tuple(
            c.chunk_id or c.document_id
            for m in matches
            for c in m.citations
            if (c.chunk_id or c.document_id)
        )
        self._audit_search(
            principal=principal,
            correlation_id=correlation_id,
            status=status,
            result_count=len(matches),
            document_ids=accessed_doc_ids,
            citation_ids=citation_ids,
        )
        if citation_ids:
            self._audit_citation_access(
                principal=principal,
                correlation_id=correlation_id,
                citation_ids=citation_ids,
                document_ids=accessed_doc_ids,
            )
        return resp

    def _audit_search(
        self,
        *,
        principal: IdentityClaims,
        correlation_id: str,
        status: str,
        result_count: int,
        document_ids: tuple[str, ...],
        citation_ids: tuple[str, ...],
    ) -> None:
        ts = _now()
        self._audit.record(
            AuditLogEntry(
                tenant_id=principal.tenant_id,
                log_id=f"trouble_case.search:{correlation_id}:{ts}",
                timestamp=ts,
                request_id=correlation_id,
                actor_id=principal.user_id,
                action="trouble_case.search",
                resource_type="trouble_case",
                resource_id=correlation_id,
                decision=status,
                reason=f"results={result_count}",  # reference count only — never the query body
                citation_ids=tuple(citation_ids),
                document_ids_used=tuple(document_ids),
            )
        )

    def _audit_citation_access(
        self,
        *,
        principal: IdentityClaims,
        correlation_id: str,
        citation_ids: tuple[str, ...],
        document_ids: tuple[str, ...],
    ) -> None:
        ts = _now()
        self._audit.record(
            AuditLogEntry(
                tenant_id=principal.tenant_id,
                log_id=f"citation.access:{correlation_id}:{ts}",
                timestamp=ts,
                request_id=correlation_id,
                actor_id=principal.user_id,
                action="citation.access",
                resource_type="citation",
                resource_id=correlation_id,
                decision="accessed",
                citation_ids=tuple(citation_ids),
                document_ids_used=tuple(document_ids),
            )
        )
