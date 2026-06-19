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
