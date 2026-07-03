"""T050/T051 — Knowledge-ops Dashboard / Safety-Telemetry / KPI facade (FR-MFG-012/028/030; §E, US5).

The three admin read-views that make the knowledge base observable, all DERIVED SYNCHRONOUSLY from
the SHARED ``AuditLogWriter`` (single source of truth, FR-MFG-030) + the in-memory
manufacturing approval metadata + the 001 evaluation/metrics primitives. There is NO parallel counter
and NO Dagster call on the request path: the Dagster ``manufacturing_dashboard_metrics``
materialization asset + daily schedule (T047a/T051a) are DEFERRED to the production track (§8 C5); in
this in-memory composition the views compute on read.

  GET /v1/manufacturing/dashboard        -> KnowledgeOpsDashboard.compute(...)   (T050)
  GET /v1/manufacturing/safety-telemetry -> SafetyTelemetry.compute(...) wrapped  (T048)
  GET /v1/manufacturing/kpi              -> PocKpiReport.compute / export(...)    (T049)

Tenant scoping is inherited from the writer's tenant-bound ``read_all`` — a cross-tenant principal
sees an empty audit log, hence 0 / empty everywhere (no disclosure).

stdlib only. Mirrors contracts/mfg-openapi.md §E + data-model §I; assertion-shape mirrors
tests/manufacturing/test_dashboard_contract.py + test_safety_telemetry.py.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from raku_rag.domain.models import IdentityClaims

# Audit-derivation primitives (action labels + entry filters) — the SINGLE source of truth shared by
# the writers (api/audit.py) and the KPI report (kpi/poc_metrics.py), so the labels cannot drift.
from raku_rag.manufacturing.api import audit as audit_derive
from raku_rag.manufacturing.domain.freshness import review_overdue_entries
from raku_rag.manufacturing.domain.metadata import ApprovalStatus
from raku_rag.manufacturing.interfaces import AuditLogWriter
from raku_rag.manufacturing.telemetry.safety_metrics import SafetyTelemetry, SOURCE_AUDIT_LOG


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class KnowledgeOpsDashboard:
    """GET /v1/manufacturing/dashboard view (FR-MFG-012, US5-1; contracts §E res 200)."""

    unanswered_question_count: int = 0
    low_rating_answers: tuple = ()
    frequent_questions: tuple = ()
    frequently_referenced_documents: tuple = ()
    obsolete_document_candidates: tuple = ()
    knowledge_gap_areas: tuple = ()
    # ★G4 freshness: docs whose review window lapsed (derived; {document_id, owner,
    # last_verified_at, review_due_date} reference rows only — additive fields).
    review_overdue_document_count: int = 0
    review_overdue_documents: tuple = ()
    correlation_id: str = ""


@dataclass(frozen=True)
class SafetyTelemetryView:
    """GET /v1/manufacturing/safety-telemetry view (FR-MFG-030, SC-MFG-013; contracts §E).

    A ``SafetyTelemetryResult``-shaped view with the API field name ``safety_gate_block_breakdown``
    AND the data-model name ``block_breakdown`` (tests read either), plus the ``source`` provenance
    marker and a correlation id.
    """

    tenant_id: str
    high_risk_query_count: int = 0
    safety_gate_block_count: int = 0
    block_breakdown: dict = field(default_factory=dict)
    axis: dict = field(default_factory=dict)
    # contracts/mfg-openapi.md §E res 200: time_range is the object {from, to, granularity}.
    # from/to are null when no input window is supplied; granularity echoes the query param.
    time_range: dict = field(default_factory=dict)
    source: str = SOURCE_AUDIT_LOG
    correlation_id: str = ""

    @property
    def safety_gate_block_breakdown(self) -> dict:
        """Contracts §E field name alias for ``block_breakdown`` (mutually exclusive)."""
        return self.block_breakdown


class DashboardService:
    """Facade computing the three US5 admin views from the shared audit log + mfg metadata."""

    def __init__(
        self,
        *,
        audit: AuditLogWriter,
        get_mfg_meta,
        all_mfg_meta,
        retention=None,
        materialized_kpi_store=None,
        today: date | None = None,
    ) -> None:
        self._audit = audit
        self._get_mfg_meta = get_mfg_meta
        # callable() -> iterable of ((tenant_id, document_id), ManufacturingDocumentMetadata)
        self._all_mfg_meta = all_mfg_meta
        self._telemetry = SafetyTelemetry(audit)
        self._retention = retention  # DataUsePolicy-backed retention (audit window) — optional
        self._materialized_kpi_store = materialized_kpi_store
        # ★G4: injectable clock for the derived review-overdue computation (None => today()).
        self._today = today

    # --- GET /v1/manufacturing/safety-telemetry (T048; FR-MFG-030, SC-MFG-013) --------------------
    def safety_telemetry(
        self,
        principal: IdentityClaims,
        *,
        collection_id: str | None = None,
        factory_id: str | None = None,
        department_id: str | None = None,
        time_range: tuple[str, str] | None = None,
        axis=None,
        granularity: str = "daily",
    ) -> SafetyTelemetryView:
        """Audit-derived safety telemetry (single source of truth). Idempotent; mutually exclusive."""
        result = self._telemetry.compute(
            principal=principal,
            collection_id=collection_id,
            factory_id=factory_id,
            department_id=department_id,
            time_range=time_range,
        )
        return SafetyTelemetryView(
            tenant_id=result.tenant_id,
            high_risk_query_count=result.high_risk_query_count,
            safety_gate_block_count=result.safety_gate_block_count,
            block_breakdown=dict(result.block_breakdown),
            axis={
                "tenant_id": result.tenant_id,
                "factory_id": factory_id,
                "department_id": department_id,
                "collection_id": collection_id,
            },
            time_range={
                "from": time_range[0] if time_range else None,
                "to": time_range[1] if time_range else None,
                "granularity": granularity,
            },
            source=SOURCE_AUDIT_LOG,
            correlation_id=f"telemetry:{_now()}",
        )

    # --- GET /v1/manufacturing/dashboard (T050; FR-MFG-012, US5-1) --------------------------------
    def knowledge_ops_dashboard(
        self,
        principal: IdentityClaims,
        *,
        collection_id: str | None = None,
        factory_id: str | None = None,
        department_id: str | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> KnowledgeOpsDashboard:
        """Surface unanswered / low-rating / frequent-docs / stale(obsolete) / knowledge-gap views.

        All counts are DERIVED from the tenant-scoped audit log (answer decisions + citation access)
        and the in-memory approval metadata — never a parallel store. Cross-tenant => 0/empty.
        """
        entries = self._audit.read_all(principal)
        answer_entries = audit_derive.answer_entries(entries)
        citation_entries = audit_derive.citation_entries(entries)

        # unanswered: answer-path decisions that did NOT assert (a safety block was recorded).
        unanswered = sum(1 for e in answer_entries if e.safety_block_reason is not None)

        # low_rating_answers: DERIVED from the audit log (single source of truth) — the answers a
        # user/reviewer rated low via record_answer_feedback (action 'feedback.low_rating', decision
        # 'low_rating'). Reference IDs only (the rated answer's correlation/resource_id or its surveyed
        # document_ids); never the comment body. Most-frequently-low-rated first.
        low_counter: Counter = Counter()
        for e in audit_derive.low_rating_feedback_entries(entries):
            ref = e.resource_id or (e.document_ids_used[0] if e.document_ids_used else None)
            if ref:
                low_counter[ref] += 1
        low_rating = tuple(ref for ref, _n in low_counter.most_common())

        # frequent_questions: grouped by the recorded reason-code signature (reference labels only,
        # never the query body — SC-MFG-010). Surfaces the topics asked most.
        reason_sigs = Counter(e.reason for e in answer_entries if e.reason)
        frequent_questions = tuple(f"{sig} (x{n})" for sig, n in reason_sigs.most_common())

        # frequently_referenced_documents: from the citation-access audit (single source of truth) —
        # the documents most surveyed/cited as evidence (reference IDs only).
        doc_hits: Counter = Counter()
        for e in citation_entries:
            for did in e.document_ids_used:
                doc_hits[did] += 1
            for cid in e.citation_ids:
                # citation_ids fall back to document_id when no chunk id; count under their id too.
                doc_hits[cid] += 1
        freq_docs = tuple(did for did, _n in doc_hits.most_common())

        # obsolete_document_candidates: from the approval metadata (obsolete / superseded docs).
        all_meta = [meta for _key, meta in self._iter_meta(principal.tenant_id)]
        obsolete = tuple(
            sorted(
                meta.document_id
                for meta in all_meta
                if meta.approval_status == ApprovalStatus.OBSOLETE
                or meta.obsolete_at is not None
                or meta.superseded_by is not None
            )
        )

        # ★G4 review_overdue: docs whose freshness window lapsed (last_verified_at +
        # review_cycle_days < today, both set). Same metadata source as obsolete candidates;
        # reference rows only (document_id/owner/dates — no content).
        overdue = review_overdue_entries(all_meta, today=self._today or date.today())

        # knowledge_gap_areas: topics with repeated unanswered / no-approved-evidence answers —
        # derived from the reason codes of the blocked answers (reference labels only).
        gap_counter: Counter = Counter()
        for e in answer_entries:
            if e.safety_block_reason is not None and e.reason:
                for code in str(e.reason).split(","):
                    code = code.strip()
                    if code:
                        gap_counter[code] += 1
        knowledge_gaps = tuple(area for area, _n in gap_counter.most_common())

        return KnowledgeOpsDashboard(
            unanswered_question_count=unanswered,
            low_rating_answers=low_rating,
            frequent_questions=frequent_questions,
            frequently_referenced_documents=freq_docs,
            obsolete_document_candidates=obsolete,
            knowledge_gap_areas=knowledge_gaps,
            review_overdue_document_count=len(overdue),
            review_overdue_documents=overdue,
            correlation_id=f"dashboard:{_now()}",
        )

    # --- GET /v1/manufacturing/kpi (T049; FR-MFG-028, SC-MFG-012) ---------------------------------
    def kpi(
        self,
        principal: IdentityClaims,
        *,
        collection_id: str | None = None,
        time_range: tuple[str, str] | None = None,
        format: str = "json",
        use_materialized: bool = True,
    ) -> dict | str:
        """Compute the full FR-MFG-028 KPI set and export it as json (dict) or csv (str)."""
        from raku_rag.manufacturing.kpi.poc_metrics import PocKpiReport

        if use_materialized and self._materialized_kpi_store is not None:
            snapshot = self._materialized_kpi_store.latest(
                principal.tenant_id,
                collection_id or "",
            )
            if snapshot is not None:
                data = dict(snapshot.metrics)
                data["materialized_at"] = snapshot.materialized_at
                data["source_ingestion_run_id"] = snapshot.source_ingestion_run_id
                data["dagster_run_id"] = snapshot.dagster_run_id
                data["source"] = "materialized"
                if format == "json":
                    return data
                if format == "csv":
                    return _kpi_dict_to_csv(data)
                raise ValueError(f"unsupported kpi format: {format!r}")

        report = PocKpiReport.compute(
            audit=self._audit,
            telemetry=self._telemetry,
            principal=principal,
            iter_meta=lambda: self._iter_meta(principal.tenant_id),
            collection_id=collection_id,
            time_range=time_range,
            today=self._today,
        )
        if format == "csv":
            return report.to_csv()
        if format == "json":
            return report.to_json()
        raise ValueError(f"unsupported kpi format: {format!r}")

    # --- helpers ----------------------------------------------------------------------------------
    def _iter_meta(self, tenant_id: str):
        """Yield ((tenant_id, document_id), metadata) for the principal's tenant only (scoped)."""
        for key, meta in self._all_mfg_meta():
            if key[0] == tenant_id:
                yield key, meta


def _kpi_dict_to_csv(data: dict) -> str:
    import csv
    import io
    import json

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["kpi", "value"])
    for key, value in data.items():
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        writer.writerow([key, value])
    return buf.getvalue()
