"""T006 — SafetyDecision / HighRiskClassification value objects (data-model §E).

Generated on the answer path, recorded into AuditLogEntry / telemetry (persisted in audit; only the
display-relevant parts surface in the Answer). These are 001-derived overlays — SafetyGate sits AFTER
the 001 GroundednessGate (contracts §4); it is NOT a new security mechanism.

Frozen value objects, no behaviour (stage-2 implements classification / gating).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ClassificationSource(str, Enum):
    """Which cascade stage flagged high-risk (any => high-risk, OR semantics; FR-MFG-015)."""

    METADATA = "metadata"
    RULE = "rule"
    KEYWORD = "keyword"
    LLM = "llm"


class SafetyBlockReason(str, Enum):
    """Mutually-exclusive single block code (FR-MFG-030).

    Normalization priority when several apply:
    (1) APPROVED_CITATION_MISSING -> (2) INSUFFICIENT_EVIDENCE -> (3) OTHER_BLOCK.
    """

    APPROVED_CITATION_MISSING = "approved_citation_missing"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    OTHER_BLOCK = "other_block"


@dataclass(frozen=True)
class HighRiskClassification:
    """High-risk determination (FR-MFG-015). Fail-safe: when ambiguous, ``is_high_risk=True``."""

    is_high_risk: bool
    reason_codes: tuple[str, ...] = ()  # e.g. equipment_stop/disassembly/electric_shock/...
    classification_source: ClassificationSource | None = None


@dataclass(frozen=True)
class SafetyDecision:
    """Safety gate outcome (FR-MFG-005/006/007, FR-MFG-030).

    Invariants (enforced by stage-2 SafetyGate, asserted by the safety hard gate tests):
    - is_high_risk & no approved+effective citation -> blocked=True,
      safety_block_reason=APPROVED_CITATION_MISSING, answer -> insufficient_evidence (safety).
    - obsolete-only evidence -> not primary evidence, obsolete_warning=True (SC-MFG-011).
    - hazardous work -> requires_onsite_confirmation=True (FR-MFG-007).
    - safety_block_reason is normalized to ONE code (1 block = 1 primary cause).
    """

    blocked: bool
    safety_block_reason: SafetyBlockReason | None = None
    obsolete_warning: bool = False
    requires_onsite_confirmation: bool = False
    approval_status_at_use: str | None = None  # ManufacturingDocumentMetadata.ApprovalStatus value
