"""T005 — Manufacturing domain entities (stdlib @dataclass; data-model §C/§D).

Normalized manufacturing metadata + relationships layer (research R5). The searchable BODY lives in
the 001 Document/Chunk; these entities are the reference layer holding entity identity and relations.

Hard rules reflected here:
- Every entity carries ``tenant_id`` (cross-tenant references forbidden — 001 tenancy, SC-MFG-008).
- ``source_document_id`` points at a 001 Document; ACL/tombstone follow that Document (stage-2 reuses
  raku_rag.core.security.acl / raku_rag.core.tenancy — no new authz here).
- Countermeasure keeps TWO independent axes: ``type`` (reference|candidate) AND ``measure_class``
  (provisional|permanent|unknown). Past-case countermeasures are shown as candidate/reference even
  when permanent (Hard Rule 4, FR-MFG-009).

Schema only — no behaviour/validation logic (stage-2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# --- Countermeasure 2-axis enums (data-model §D, FR-MFG-008/009) ---


class CountermeasureType(str, Enum):
    """Display / evidence class. NOT an official work instruction."""

    REFERENCE = "reference"
    CANDIDATE = "candidate"


class MeasureClass(str, Enum):
    """Nature of the countermeasure."""

    PROVISIONAL = "provisional"  # 暫定
    PERMANENT = "permanent"  # 恒久
    UNKNOWN = "unknown"  # 分類不明


# --- Organization / equipment hierarchy ---


@dataclass
class Factory:
    """ACL / permission territory unit (FR-MFG-013 factory mapping)."""

    tenant_id: str
    factory_id: str
    name: str = ""


@dataclass
class ProductionLine:
    tenant_id: str
    line_id: str
    factory_id: str
    name: str = ""


@dataclass
class Process:
    tenant_id: str
    process_id: str
    factory_id: str
    process_name: str = ""
    line_id: str | None = None


@dataclass
class Equipment:
    tenant_id: str
    equipment_id: str
    factory_id: str
    equipment_name: str = ""
    model_no: str | None = None
    line_id: str | None = None
    process_id: str | None = None


@dataclass
class AlarmCode:
    tenant_id: str
    alarm_id: str
    equipment_id: str
    code: str = ""
    description: str = ""


# --- Product / part / customer / defect taxonomy ---


@dataclass
class Product:
    tenant_id: str
    product_id: str
    product_name: str = ""


@dataclass
class Part:
    tenant_id: str
    part_id: str
    part_no: str = ""


@dataclass
class Customer:
    """High sensitivity; ACL-relevant (SC-MFG-008)."""

    tenant_id: str
    customer_id: str
    name: str = ""


@dataclass
class DefectType:
    tenant_id: str
    defect_id: str
    defect_name: str = ""


@dataclass
class FailureMode:
    tenant_id: str
    failure_mode_id: str
    name: str = ""
    description: str = ""  # cause description


# --- Trouble cases & countermeasures ---


@dataclass
class TroubleCase:
    tenant_id: str
    trouble_case_id: str
    symptom: str = ""
    equipment_id: str | None = None
    process_id: str | None = None
    failure_mode_id: str | None = None
    occurred_at: str | None = None  # ISO timestamp
    source_document_id: str | None = None  # FK -> 001 Document


@dataclass
class Countermeasure:
    """TWO independent axes (data-model §D). Past-case is candidate/reference even when permanent."""

    tenant_id: str
    measure_id: str
    trouble_case_id: str
    description: str = ""
    type: CountermeasureType = CountermeasureType.REFERENCE
    measure_class: MeasureClass = MeasureClass.UNKNOWN
    source_document_id: str | None = None  # FK -> 001 Document


# --- Document-backed knowledge entities ---


@dataclass
class WorkInstruction:
    """Approval metadata flows via ManufacturingDocumentMetadata (§B), not duplicated here."""

    tenant_id: str
    work_instruction_id: str
    document_id: str  # FK -> 001 Document
    equipment_id: str | None = None
    process_id: str | None = None


@dataclass
class InspectionChecklist:
    """Sourced from an imported document OR a DraftArtifact (draft)."""

    tenant_id: str
    checklist_id: str
    document_id: str | None = None  # imported source
    artifact_id: str | None = None  # DraftArtifact origin (draft)


@dataclass
class QualityIssue:
    tenant_id: str
    quality_issue_id: str
    defect_id: str
    product_id: str | None = None
    customer_id: str | None = None
    cause: str = ""
    countermeasure: str = ""
    source_document_id: str | None = None  # FK -> 001 Document


@dataclass
class TrainingMaterial:
    """Sourced from an imported document OR a DraftArtifact (draft)."""

    tenant_id: str
    training_id: str
    document_id: str | None = None  # imported source
    artifact_id: str | None = None  # DraftArtifact origin (draft)


# --- Draft-derived knowledge entities (T045; US4, data-model §F/§C) ---
#
# A DraftArtifact (status=draft, created_by=ai) is the ORIGIN of a draft InspectionChecklist /
# TrainingMaterial. These helpers wire that derivation WITHOUT importing the draft schema at module
# load time (avoid a cycle): they only read ``artifact_id``/``collection_id``/``type`` off a
# duck-typed DraftArtifact. The derived entity carries ``artifact_id`` (not ``document_id``) so it is
# unambiguously a draft-origin record — never treated as an approved imported source until a reviewer
# approves the originating draft (Hard Rule 1).


def inspection_checklist_from_draft(artifact) -> "InspectionChecklist":
    """Build a draft-origin InspectionChecklist from a CHECKLIST DraftArtifact (artifact_id set)."""
    return InspectionChecklist(
        tenant_id=artifact.tenant_id,
        checklist_id=artifact.artifact_id,
        document_id=None,  # not an imported source — this is draft-origin
        artifact_id=artifact.artifact_id,
    )


def training_material_from_draft(artifact) -> "TrainingMaterial":
    """Build a draft-origin TrainingMaterial from a TRAINING DraftArtifact (artifact_id set)."""
    return TrainingMaterial(
        tenant_id=artifact.tenant_id,
        training_id=artifact.artifact_id,
        document_id=None,  # not an imported source — this is draft-origin
        artifact_id=artifact.artifact_id,
    )


# --- Retrieval result wrapper (TroubleCaseRetriever return shape, contracts §5) ---


@dataclass(frozen=True)
class TroubleCaseResult:
    """A similar TroubleCase resolved with its FailureMode + Countermeasures and citations.

    ``countermeasures`` keep both axes so callers can split provisional vs permanent and apply the
    candidate/reference normalization (Hard Rule 4, FR-MFG-009).
    """

    trouble_case: TroubleCase
    failure_mode: FailureMode | None = None
    countermeasures: tuple[Countermeasure, ...] = ()
    citation_ids: tuple[str, ...] = ()
    relevance_score: float = 0.0
