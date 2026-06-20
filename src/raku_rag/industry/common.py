"""Shared deterministic runtime primitives for industry solution-layer UAT.

These classes are deliberately small and stdlib-only. They make the industry use cases executable
without pretending to be the final production adapters: every response carries citations, risk
decisions, draft state, audit events, and dashboard counters so the UAT tests can prove behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndustryCitation:
    document_id: str
    document_type: str
    approval_status: str = "approved"
    effective_date: str | None = "2026-01-10"
    page: int | None = None
    section: str | None = None
    sheet_name: str | None = None
    cell_range: str | None = None
    row_id: str | None = None
    role: str = "formal"


@dataclass(frozen=True)
class IndustryAuditEvent:
    action: str
    decision: str
    resource_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class IndustryAnswer:
    status: str
    text: str
    citations: tuple[IndustryCitation, ...] = ()
    risk_gate: str | None = None
    review_required: bool = False
    blocked: bool = False
    warnings: tuple[str, ...] = ()
    table_rows: tuple[dict, ...] = ()
    audit_events: tuple[IndustryAuditEvent, ...] = ()

    @property
    def insufficient_evidence(self) -> bool:
        return self.status == "insufficient_evidence"


@dataclass(frozen=True)
class IndustryDraft:
    artifact_type: str
    status: str = "draft"
    reviewer_group: str | None = None
    source_document_ids: tuple[str, ...] = ()
    source_citations: tuple[IndustryCitation, ...] = ()
    auto_approved: bool = False
    compliance_review_status: str | None = None
    disclosure_evidence_ids: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    audit_events: tuple[IndustryAuditEvent, ...] = ()


@dataclass(frozen=True)
class IndustryDashboard:
    metrics: dict
    drilldowns: dict = field(default_factory=dict)
    audit_events: tuple[IndustryAuditEvent, ...] = ()


@dataclass(frozen=True)
class IndustryUser:
    user_id: str
    tenant_id: str = "tenant_alpha"
    role: str = "standard_user"
    property_scope: tuple[str, ...] = ()
    unit_scope: tuple[str, ...] = ()
    fund_scope: tuple[str, ...] = ()
    research_memo_access: bool = False
    personal_data_access: bool = False
    amount_access: bool = False
    admin: bool = False


@dataclass(frozen=True)
class IndustryDocument:
    document_id: str
    document_type: str
    tenant_id: str = "tenant_alpha"
    approval_status: str = "approved"
    property_id: str | None = None
    unit_id: str | None = None
    owner_id: str | None = None
    fund_id: str | None = None
    confidential_category: str | None = None
    personal_data_category: str | None = None
    citation: IndustryCitation | None = None

    @property
    def approved(self) -> bool:
        return self.approval_status == "approved"


class IndustryAuditLog:
    def __init__(self) -> None:
        self._events: list[IndustryAuditEvent] = []

    def record(
        self, action: str, decision: str, resource_id: str | None = None, **metadata
    ) -> None:
        self._events.append(
            IndustryAuditEvent(
                action=action,
                decision=decision,
                resource_id=resource_id,
                metadata=dict(metadata),
            )
        )

    def all(self) -> tuple[IndustryAuditEvent, ...]:
        return tuple(self._events)

    def count(self, action: str) -> int:
        return sum(1 for event in self._events if event.action == action)

    def has(self, action: str) -> bool:
        return any(event.action == action for event in self._events)
