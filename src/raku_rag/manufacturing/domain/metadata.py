"""T005 — ManufacturingDocumentMetadata + enums (stdlib @dataclass, mirrors domain/models.py style).

Solution layer ON TOP of 001. This metadata is stored in 001 ``Document.metadata`` /
``Chunk.metadata`` (JSON) and read by 001 metadata filter ([base:FR-010]) plus SafetyGate /
HighRiskClassifier. Every record carries ``tenant_id`` (001 tenancy is mandatory, [base:FR-021]).

Authoritative field definitions: specs/002-manufacturing-field-knowledge-rag/data-model.md §B.
No behaviour here — schema + value enums only (stage-2 implements enrichment/validation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DocumentKind(str, Enum):
    """``document_type`` / ``document_kind`` enumeration (data-model §B)."""

    WORK_INSTRUCTION = "work_instruction"
    INSPECTION = "inspection"
    QUALITY_REPORT = "quality_report"
    TROUBLE_REPORT = "trouble_report"
    MINUTES = "minutes"
    LEDGER = "ledger"
    DRAWING = "drawing"
    TRAINING = "training"


class ApprovalStatus(str, Enum):
    """Document approval lifecycle (FR-MFG-004). State machine in data-model State Transitions."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    OBSOLETE = "obsolete"


class ApprovalSource(str, Enum):
    """imported = upstream system is source of truth; workflow = this layer's lightweight flow."""

    IMPORTED = "imported"
    WORKFLOW = "workflow"


@dataclass
class ManufacturingDocumentMetadata:
    """Comprehensive manufacturing + approval metadata for a 001 Document (data-model §B).

    Stored in ``Document.metadata`` and propagated to ``Chunk.metadata``. ``tenant_id`` is the
    hard isolation boundary; ``document_id`` is the FK into the 001 Document.
    """

    tenant_id: str
    document_id: str  # FK -> 001 Document.document_id

    # --- manufacturing tags ---
    equipment: str | None = None  # equipment name
    model_no: str | None = None
    alarm_code: str | None = None
    defect_type: str | None = None
    process: str | None = None  # process name
    part_no: str | None = None
    customer: str | None = None  # high sensitivity, ACL-relevant (SC-MFG-008)
    document_kind: DocumentKind | None = None  # a.k.a. document_type (enum value required at use)

    # entity FKs (aggregation / ACL mapping; FR-MFG-013)
    process_id: str | None = None
    equipment_id: str | None = None

    # --- safety / quality classification tags (HighRiskClassifier input, FR-MFG-015) ---
    safety_category: str | None = None
    quality_category: str | None = None
    equipment_operation_category: str | None = None
    hazard_tags: tuple[str, ...] = ()  # e.g. 設備停止/分解/感電/高温/高圧/薬品/重量物/安全装置
    regulation_refs: tuple[str, ...] = ()  # e.g. ISO_12100_2010 / JIS_B_9700_2013

    # --- approval metadata (FR-MFG-004/004a) ---
    approval_status: ApprovalStatus = ApprovalStatus.DRAFT
    effective_date: str | None = None  # ISO date; valid = not future, not expired
    approved_by: str | None = None
    approved_at: str | None = None  # ISO timestamp
    obsolete_at: str | None = None
    superseded_by: str | None = None  # document_id of the superseding doc
    approval_source: ApprovalSource = ApprovalSource.WORKFLOW

    # free-form extension carried through 001 metadata JSON
    extra: dict = field(default_factory=dict)

    def to_mapping(self) -> dict:
        """JSON-/jsonb-safe dict (enums→values, tuples→lists) for persisting in Document.metadata.

        Lets the per-document manufacturing metadata survive a Postgres jsonb round-trip so the safety
        overlay can run over the deployed ProductionSystem (P1-1), not only the in-memory MvpSystem.
        """
        return {
            "tenant_id": self.tenant_id,
            "document_id": self.document_id,
            "equipment": self.equipment,
            "model_no": self.model_no,
            "alarm_code": self.alarm_code,
            "defect_type": self.defect_type,
            "process": self.process,
            "part_no": self.part_no,
            "customer": self.customer,
            "document_kind": self.document_kind.value if self.document_kind else None,
            "process_id": self.process_id,
            "equipment_id": self.equipment_id,
            "safety_category": self.safety_category,
            "quality_category": self.quality_category,
            "equipment_operation_category": self.equipment_operation_category,
            "hazard_tags": list(self.hazard_tags),
            "regulation_refs": list(self.regulation_refs),
            "approval_status": self.approval_status.value,
            "effective_date": self.effective_date,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "obsolete_at": self.obsolete_at,
            "superseded_by": self.superseded_by,
            "approval_source": self.approval_source.value,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_mapping(cls, data: object) -> "ManufacturingDocumentMetadata":
        """Reconstruct from a dict (e.g. Postgres jsonb) or pass an existing instance through."""
        if isinstance(data, cls):
            return data
        m = dict(data)  # type: ignore[arg-type]

        def _enum(enum_cls, value, default):
            if value is None:
                return default
            if isinstance(value, enum_cls):
                return value
            try:
                return enum_cls(value)
            except ValueError:
                return default

        return cls(
            tenant_id=str(m.get("tenant_id") or ""),
            document_id=str(m.get("document_id") or ""),
            equipment=m.get("equipment"),
            model_no=m.get("model_no"),
            alarm_code=m.get("alarm_code"),
            defect_type=m.get("defect_type"),
            process=m.get("process"),
            part_no=m.get("part_no"),
            customer=m.get("customer"),
            document_kind=_enum(DocumentKind, m.get("document_kind"), None),
            process_id=m.get("process_id"),
            equipment_id=m.get("equipment_id"),
            safety_category=m.get("safety_category"),
            quality_category=m.get("quality_category"),
            equipment_operation_category=m.get("equipment_operation_category"),
            hazard_tags=tuple(m.get("hazard_tags") or ()),
            regulation_refs=tuple(m.get("regulation_refs") or ()),
            approval_status=_enum(ApprovalStatus, m.get("approval_status"), ApprovalStatus.DRAFT),
            effective_date=m.get("effective_date"),
            approved_by=m.get("approved_by"),
            approved_at=m.get("approved_at"),
            obsolete_at=m.get("obsolete_at"),
            superseded_by=m.get("superseded_by"),
            approval_source=_enum(
                ApprovalSource, m.get("approval_source"), ApprovalSource.WORKFLOW
            ),
            extra=dict(m.get("extra") or {}),
        )
