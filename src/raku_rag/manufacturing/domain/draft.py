"""T006 — DraftArtifact schema (data-model §F, FR-MFG-010/010a/010b, G1).

AI-generated output. ALWAYS created with status=draft and NEVER auto-approved (Hard Rule 1,
SC-MFG-007). Reviewer (single or group) approval is the only path to ``approved``; FAQ is treated
like every other draft. All transitions are recorded in AuditLogEntry (FR-MFG-021).

State machine (data-model §F):
    draft -> in_review -> approved | rejected | archived ;  draft -> archived

Schema + enums only — no transition/validation behaviour (stage-2 ReviewWorkflow / DraftGenerator).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DraftType(str, Enum):
    CHECKLIST = "checklist"
    TROUBLE_REPORT = "trouble_report"
    QUALITY_REPORT = "quality_report"
    TRAINING = "training"
    FAQ = "faq"


class DraftStatus(str, Enum):
    DRAFT = "draft"  # default; AI cannot transition past this automatically
    IN_REVIEW = "in_review"
    APPROVED = "approved"  # reviewer decision only
    REJECTED = "rejected"
    ARCHIVED = "archived"


class CreatedBy(str, Enum):
    AI = "ai"
    USER = "user"


@dataclass
class DraftArtifact:
    """AI/user draft output (data-model §F). Default status=draft is the central safety invariant."""

    tenant_id: str
    artifact_id: str
    type: DraftType
    collection_id: str | None = None
    status: DraftStatus = DraftStatus.DRAFT  # default draft (Hard Rule 1)

    # --- generation provenance (audit trail, FR-MFG-010b) ---
    source_citations: tuple[str, ...] = ()  # references to 001 Citation (citation ids)
    source_document_ids: tuple[str, ...] = ()
    template_id: str | None = None
    created_by: CreatedBy | None = None  # ai | user
    created_at: str | None = None  # ISO timestamp
    audit_log_ref: str | None = None  # AuditLogEntry.log_id

    # --- review fields (FR-MFG-010a) ---
    reviewer_id: str | None = None
    reviewer_role: str | None = None
    reviewer_group: str | None = None
    assigned_at: str | None = None
    reviewed_at: str | None = None
    review_comment: str | None = None
    approval_decision: str | None = None  # approve | reject (reviewer's explicit decision)
    review_status: str | None = None

    # --- publish fields (issue 0019; approved -> published-as-knowledge) ---
    # Set ONLY by DraftService.publish (a separate, attributable HUMAN action after approval):
    # the 001 Document the approved draft was ingested as, who published it, and when.
    published_document_id: str | None = None
    published_by: str | None = None
    published_at: str | None = None  # ISO timestamp

    # free-form generated content payload (not load-bearing for schema gates)
    content: dict = field(default_factory=dict)
