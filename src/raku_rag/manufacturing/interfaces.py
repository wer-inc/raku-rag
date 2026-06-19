"""T008 — Abstract interfaces for the manufacturing solution layer (contracts/mfg-interfaces.md).

This layer REUSES the 13 base abstractions from raku_rag.interfaces.base and adds only the
manufacturing-specific abstractions below. It does NOT define new authz / search / deletion
mechanisms — those are 001's ACL pre-filter / VectorStore tombstone / tenancy, reused by stage-2.

Signatures follow contracts/mfg-interfaces.md §2–§8. ABCs only — no behaviour (stage-2 implements).
Concrete types referenced here are the stdlib @dataclass domain models in
raku_rag.manufacturing.domain.*; ``Citation`` / ``IdentityClaims`` are reused from 001 domain.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from raku_rag.domain.models import Citation, IdentityClaims
from raku_rag.manufacturing.domain.audit import (
    AuditLogEntry,
    SafetyTelemetryResult,
    TelemetryAxis,
)
from raku_rag.manufacturing.domain.draft import DraftArtifact, DraftType
from raku_rag.manufacturing.domain.entities import TroubleCaseResult
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.domain.policy import DataUsePolicy, RetentionConfig
from raku_rag.manufacturing.domain.safety import HighRiskClassification, SafetyDecision


@dataclass(frozen=True)
class ApprovalState:
    """Result of an ApprovalWorkflow transition / external import (contracts §2)."""

    tenant_id: str
    document_id: str
    approval_status: str  # ApprovalStatus value
    approval_source: str  # ApprovalSource value
    effective_date: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None


# --- §2 Ingestion: metadata enrichment + lightweight approval workflow ---


class MetadataEnricher(ABC):
    """Attach manufacturing + approval metadata to Document.metadata at ingest (FR-MFG-003/004/004a)."""

    @abstractmethod
    def enrich(self, doc_ref: str, raw_metadata: dict) -> ManufacturingDocumentMetadata: ...


class ApprovalWorkflow(ABC):
    """Lightweight draft->pending_review->approved->obsolete approval (FR-MFG-004)."""

    @abstractmethod
    def transition(
        self, tenant_id: str, document_id: str, to_status: str, actor: IdentityClaims
    ) -> ApprovalState: ...

    @abstractmethod
    def import_external(
        self, tenant_id: str, document_id: str, external: dict
    ) -> ApprovalState:
        """Import approval_source=imported as the source of truth (FR-MFG-004a)."""


# --- §3 High-risk classification ---


class HighRiskClassifier(ABC):
    """3-stage cascade: metadata -> rule+keyword intent -> (only when ambiguous) 001 LLMProvider.

    Any stage hitting => is_high_risk=True (OR). Ambiguous => True (fail-safe) (FR-MFG-015).
    """

    @abstractmethod
    def classify(
        self, query: str, candidate_metadata: list[ManufacturingDocumentMetadata]
    ) -> HighRiskClassification: ...


# --- §4 Safety gate (sits AFTER the 001 GroundednessGate) ---


class SafetyGate(ABC):
    """Safe-side control downstream of 001 groundedness gate (FR-MFG-005/006/007, research R3)."""

    @abstractmethod
    def evaluate(
        self,
        classification: HighRiskClassification,
        candidate_citations: list[Citation],
        candidate_metadata: list[ManufacturingDocumentMetadata],
    ) -> SafetyDecision: ...


# --- §5 Trouble-case retrieval ---


class TroubleCaseRetriever(ABC):
    """Find similar past cases via 001 retrieval (ACL pre-filter), splitting provisional/permanent.

    Past-case countermeasures are normalized to candidate/reference even when permanent
    (Hard Rule 4, FR-MFG-009).
    """

    @abstractmethod
    def find_similar(
        self, symptom_query: str, principal: IdentityClaims
    ) -> list[TroubleCaseResult]: ...


# --- §6 Draft generation + review workflow ---


class DraftGenerator(ABC):
    """Generate a DraftArtifact. Result is ALWAYS status=draft (Hard Rule 1, SC-MFG-007)."""

    @abstractmethod
    def generate(
        self,
        kind: DraftType,
        context_citations: list[Citation],
        template_id: str | None,
        actor: IdentityClaims,
    ) -> DraftArtifact: ...


class ReviewWorkflow(ABC):
    """draft->in_review->approved|rejected|archived. approved = reviewer only; all transitions audited."""

    @abstractmethod
    def assign(self, artifact_id: str, reviewer_id_or_group: str) -> DraftArtifact: ...

    @abstractmethod
    def decide(
        self, artifact_id: str, reviewer: IdentityClaims, decision: str, comment: str
    ) -> DraftArtifact: ...


# --- §7 Governance: data-use policy / no-train guard / retention ---


class DataUsePolicyStore(ABC):
    """Per-tenant data-use policy (defaults no_train_default=True, opt_in=False)."""

    @abstractmethod
    def get(self, tenant_id: str) -> DataUsePolicy: ...

    @abstractmethod
    def update(self, tenant_id: str, patch: dict, actor: IdentityClaims) -> DataUsePolicy:
        """Changes are audited (FR-MFG-019)."""


class NoTrainGuard(ABC):
    """Enforce no-train (SC-MFG-009) and capability availability under no-train requirement (GQ1)."""

    @abstractmethod
    def assert_no_train(self, tenant_id: str, data_kind: str) -> None:
        """Forbid training / cross-tenant / cross-improvement use without opt-in."""

    @abstractmethod
    def capability_allowed(self, tenant_id: str, capability: str) -> bool:
        """False when provider_no_train_required and no no-train provider exists (GQ1=block)."""


class RetentionManager(ABC):
    """Effective retention (default customer 365d / audit 365d, GQ2). Expiry delegates to 001 tombstone."""

    @abstractmethod
    def effective_retention(self, tenant_id: str) -> RetentionConfig: ...


# --- §8 Audit writer + safety telemetry ---


class AuditLogWriter(ABC):
    """Tenant-scoped, reference-IDs-only, hash-chained audit writer (SC-MFG-010, Base CR-001-A)."""

    @abstractmethod
    def record(self, entry: AuditLogEntry) -> None: ...


class SafetyTelemetry(ABC):
    """Aggregate audit log (single source of truth) into safety telemetry (FR-MFG-030)."""

    @abstractmethod
    def aggregate(
        self,
        tenant_id: str,
        *,
        axis: TelemetryAxis,
        time_range: tuple[str, str],
    ) -> SafetyTelemetryResult: ...
