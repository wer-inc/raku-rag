"""Common industry-solution framework primitives.

This module implements the 010 Industry Solution Framework as a small, deterministic runtime layer.
It is intentionally independent of a specific web framework or database adapter: production APIs and
repositories can assemble the same profiles, schemas, policies, and draft workflow contracts behind
NestJS/Postgres, while the local UAT runtime can exercise them in memory.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from raku_rag.industry.common import IndustryCitation

COMMON_METADATA_FIELDS = (
    "tenant_id",
    "collection_id",
    "document_id",
    "approval_status",
    "effective_date",
    "access_scope",
    "acl_tags",
    "no_train_policy_ref",
    "retention_policy_ref",
)

_HIGH_RISK_DECISIONS = frozenset(
    {"high_risk", "review_required", "blocked", "insufficient_evidence"}
)
_FIELD_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object"})


@dataclass(frozen=True)
class MetadataFieldDefinition:
    field_name: str
    display_name: str
    field_type: str = "string"
    required: bool = False
    searchable: bool = False
    filterable: bool = False
    facetable: bool = False
    pii_category: str | None = None
    validation_rule: str | None = None
    allowed_values: tuple[str, ...] = ()
    default_value: object | None = None


@dataclass(frozen=True)
class MetadataSchema:
    schema_id: str
    industry_id: str
    version: int
    fields: tuple[MetadataFieldDefinition, ...]
    required_fields: tuple[str, ...] = ()
    indexed_fields: tuple[str, ...] = ()
    pii_fields: tuple[str, ...] = ()
    retention_fields: tuple[str, ...] = ()
    validation_rules: tuple[str, ...] = ()

    def field_map(self) -> dict[str, MetadataFieldDefinition]:
        return {field.field_name: field for field in self.fields}


@dataclass(frozen=True)
class MetadataValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentTypeDefinition:
    document_type: str
    industry_id: str
    display_name: str
    required_metadata_fields: tuple[str, ...] = ()
    default_approval_policy: str = "default_approval"
    default_retention_policy: str = "default_retention"
    default_access_scope: str = "tenant"
    citation_policy: str = "source_citation_required"


@dataclass(frozen=True)
class EntityTypeDefinition:
    entity_type: str
    industry_id: str
    display_name: str
    id_field: str
    label_field: str
    relationship_fields: tuple[str, ...] = ()
    metadata_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    industry_id: str
    name: str
    description: str = ""
    input_schema_id: str = ""
    retrieval_profile: str = "default"
    risk_policy_id: str = "default_risk"
    required_evidence_policy_id: str = "default_evidence"
    output_schema_id: str = ""
    draft_artifact_type: str | None = None
    review_required: bool = False
    audit_events: tuple[str, ...] = ()
    kpi_events: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeywordRiskRule:
    rule_id: str
    category: str
    keywords: tuple[str, ...]
    decision: str = "review_required"
    confidence: float = 0.9
    metadata_matches: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskPolicy:
    risk_policy_id: str
    industry_id: str
    version: int = 1
    risk_categories: tuple[str, ...] = ()
    keyword_rules: tuple[KeywordRiskRule, ...] = ()
    metadata_rules: tuple[KeywordRiskRule, ...] = ()
    intent_classification_rules: tuple[KeywordRiskRule, ...] = ()
    default_action: str = "allow"
    escalation_policy: str = "human_review"
    uncertain_case_action: str = "review_required"
    llm_classifier_prompt: str | None = None


@dataclass(frozen=True)
class RiskDecision:
    risk_decision_id: str
    industry_id: str
    risk_categories: tuple[str, ...]
    matched_rules: tuple[str, ...]
    confidence: float
    decision: str
    reason: str
    policy_version: int

    @property
    def high_risk(self) -> bool:
        return bool(self.risk_categories) or self.decision in _HIGH_RISK_DECISIONS


@dataclass(frozen=True)
class RequiredEvidencePolicy:
    policy_id: str
    industry_id: str
    required_approval_status: str = "approved"
    require_effective_date_valid: bool = True
    allow_obsolete_as_reference: bool = False
    allow_draft_as_reference: bool = False
    minimum_citation_count: int = 1
    citation_types_allowed: tuple[str, ...] = ()
    insufficient_evidence_behavior: str = "insufficient_evidence"


@dataclass(frozen=True)
class EvidenceDecision:
    passed: bool
    status: str
    valid_citations: tuple[IndustryCitation, ...] = ()
    invalid_citations: tuple[IndustryCitation, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowRequest:
    tenant_id: str
    workflow_id: str
    query: str
    collection_id: str | None = None
    industry_id: str | None = None
    actor_id: str = ""
    metadata: dict = field(default_factory=dict)
    citations: tuple[IndustryCitation, ...] = ()
    source_document_ids: tuple[str, ...] = ()
    draft_artifact_type: str | None = None
    payload: dict = field(default_factory=dict)
    uncertain: bool = False


@dataclass(frozen=True)
class FrameworkAuditEvent:
    tenant_id: str
    industry_id: str
    workflow_id: str
    action: str
    decision: str
    actor_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FrameworkCostEvent:
    tenant_id: str
    industry_id: str
    workflow_id: str
    kind: str
    units: int = 1
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowResult:
    status: str
    text: str
    profile: "IndustryProfile"
    workflow: WorkflowDefinition
    risk_decision: RiskDecision
    evidence_decision: EvidenceDecision
    citations: tuple[IndustryCitation, ...] = ()
    draft_artifact: "FrameworkDraftArtifact | None" = None
    audit_events: tuple[FrameworkAuditEvent, ...] = ()
    cost_events: tuple[FrameworkCostEvent, ...] = ()
    review_required: bool = False
    blocked: bool = False


@dataclass(frozen=True)
class IndustryWorkflowHooks:
    retrieve: (
        Callable[
            [WorkflowRequest, "IndustryProfile", WorkflowDefinition], tuple[IndustryCitation, ...]
        ]
        | None
    ) = None
    answer: (
        Callable[
            [WorkflowRequest, "IndustryProfile", WorkflowDefinition, tuple[IndustryCitation, ...]],
            str,
        ]
        | None
    ) = None
    citation_access: (
        Callable[
            [WorkflowRequest, "IndustryProfile", WorkflowDefinition, tuple[IndustryCitation, ...]],
            None,
        ]
        | None
    ) = None
    audit: Callable[[FrameworkAuditEvent], None] | None = None
    cost: Callable[[FrameworkCostEvent], None] | None = None


@dataclass(frozen=True)
class ApprovalPolicy:
    policy_id: str
    industry_id: str
    approval_statuses: tuple[str, ...] = ("draft", "pending_review", "approved", "obsolete")
    external_approval_source_allowed: bool = True
    lightweight_workflow_allowed: bool = True
    effective_date_required: bool = True
    obsolete_warning_required: bool = True


@dataclass(frozen=True)
class ACLMappingPolicy:
    policy_id: str
    industry_id: str
    metadata_fields_to_acl: tuple[str, ...] = ()
    role_mappings: dict[str, str] = field(default_factory=dict)
    department_mappings: dict[str, str] = field(default_factory=dict)
    resource_scope_rules: tuple[str, ...] = ()
    deny_by_default: bool = True
    pre_filter_required: bool = True


@dataclass(frozen=True)
class DraftArtifactTypeDefinition:
    artifact_type: str
    industry_id: str
    display_name: str
    output_schema: dict = field(default_factory=dict)
    required_citations: int = 1
    review_required: bool = True
    auto_approve_allowed: bool = False
    retention_policy: str = "default_retention"
    export_formats: tuple[str, ...] = ("json",)


@dataclass(frozen=True)
class DraftReviewPolicy:
    policy_id: str
    industry_id: str
    allowed_transitions: tuple[tuple[str, str], ...] = (
        ("draft", "in_review"),
        ("in_review", "approved"),
        ("in_review", "rejected"),
        ("approved", "archived"),
        ("rejected", "archived"),
    )
    reviewer_roles: tuple[str, ...] = ("reviewer", "admin")
    required_review_fields: tuple[str, ...] = ("decision",)
    audit_required: bool = True
    multi_step_review_supported: bool = False


@dataclass(frozen=True)
class FrameworkDraftArtifact:
    artifact_id: str
    industry_id: str
    artifact_type: str
    status: str = "draft"
    created_by: str = "ai"
    reviewer_id: str | None = None
    reviewer_group: str | None = None
    source_citations: tuple[IndustryCitation, ...] = ()
    source_document_ids: tuple[str, ...] = ()
    generated_at: str = ""
    template_id: str | None = None
    audit_log_ref: str | None = None
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class KPIDefinition:
    kpi_id: str
    industry_id: str
    name: str
    description: str
    formula: str
    event_sources: tuple[str, ...] = ()
    aggregation_window: str = "daily"
    dashboard_visibility: tuple[str, ...] = ("admin",)
    target_value: float | None = None


@dataclass(frozen=True)
class KPIValue:
    kpi_id: str
    industry_id: str
    value: float
    tenant_id: str = ""
    source_event_count: int = 0
    dimensions: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DashboardWidgetDefinition:
    widget_id: str
    industry_id: str
    name: str
    kpi_ids: tuple[str, ...]
    filters: dict = field(default_factory=dict)
    required_role: str = "admin"
    data_source: str = "audit"


@dataclass(frozen=True)
class DashboardResult:
    tenant_id: str
    industry_id: str
    widgets: tuple[dict, ...]
    kpis: tuple[KPIValue, ...]
    denied_widget_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GovernanceProfile:
    governance_profile_id: str
    industry_id: str
    no_train_policy_ref: str = "default_no_train"
    audit_event_definitions: tuple[str, ...] = ()
    retention_policy_refs: tuple[str, ...] = ("default_retention",)
    pii_policy_refs: tuple[str, ...] = ()
    provider_governance_requirements: tuple[str, ...] = ("no_train_default", "audit_required")
    ai_governance_notes: tuple[str, ...] = ()
    ismap_readiness_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class GovernanceStatus:
    industry_id: str
    status: str
    no_train_enforced: bool
    audit_ready: bool
    provider_ready: bool
    retention_ready: bool
    facts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RecordRetentionPolicy:
    policy_id: str
    industry_id: str
    retention_days: int = 2555
    export_supported: bool = True
    delete_supported: bool = True
    audit_required: bool = True
    legal_hold_supported: bool = True


@dataclass(frozen=True)
class RetentionDecision:
    document_id: str
    industry_id: str
    retention_policy_ref: str
    retain_until: str
    export_allowed: bool
    delete_allowed: bool
    audit_required: bool


@dataclass(frozen=True)
class AuditEventDefinition:
    event_type: str
    industry_id: str
    required_fields: tuple[str, ...] = ("tenant_id", "actor_id", "action", "decision")
    pii_redaction_required: bool = True
    retention_policy: str = "default_retention"
    exportable: bool = True
    tenant_isolated: bool = True


@dataclass(frozen=True)
class EvaluationProfile:
    profile_id: str
    industry_id: str
    metrics: tuple[str, ...] = ("groundedness", "citation_required", "leakage_zero")
    baseline_strategy: str = "golden_set"
    hard_gates: tuple[str, ...] = ("tenant_isolation", "acl_leakage_zero")
    regression_gates: tuple[str, ...] = ("answer_quality",)
    evaluation_dataset_requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegulatedActivityPolicy:
    policy_id: str
    industry_id: str
    regulated_activity_categories: tuple[str, ...] = ()
    allowed_ai_actions: tuple[str, ...] = ("retrieve", "summarize", "draft", "flag")
    restricted_ai_actions: tuple[str, ...] = ("customer_facing_final",)
    prohibited_ai_actions: tuple[str, ...] = ("advice_finalization", "order_execution")
    human_review_required: bool = True
    escalation_roles: tuple[str, ...] = ("compliance",)
    disclaimer_policy: str = "review_required"
    audit_required: bool = True


@dataclass(frozen=True)
class AdviceBoundaryPolicy:
    policy_id: str
    industry_id: str
    advice_like_intent_categories: tuple[str, ...] = ()
    prohibited_outputs: tuple[str, ...] = ("buy_sell_recommendation", "suitability_judgment")
    allowed_outputs: tuple[str, ...] = ("source_fact_summary", "missing_evidence", "draft")
    required_response_behavior: str = "blocked_or_review_required"
    human_review_required: bool = True
    user_facing_disclaimer: str = "human_review_required"
    internal_only_flag: bool = True


@dataclass(frozen=True)
class DisclosureEvidencePolicy:
    policy_id: str
    industry_id: str
    required_source_document_types: tuple[str, ...] = ()
    require_latest_approved: bool = True
    require_effective_date_valid: bool = True
    allowed_draft_sources: tuple[str, ...] = ()
    obsolete_source_behavior: str = "exclude_formal_evidence"
    contradiction_check_required: bool = True
    citation_requirement: str = "source_citation_required"


@dataclass(frozen=True)
class ComplianceReviewPolicy:
    policy_id: str
    industry_id: str
    review_required_artifact_types: tuple[str, ...] = ()
    reviewer_roles: tuple[str, ...] = ("compliance",)
    review_states: tuple[str, ...] = (
        "draft",
        "in_review",
        "changes_requested",
        "compliance_approved",
        "business_approved",
        "rejected",
        "archived",
    )
    auto_approve_allowed: bool = False
    required_review_fields: tuple[str, ...] = ("decision", "reviewer_id")
    audit_required: bool = True
    retention_required: bool = True


@dataclass(frozen=True)
class IndustryProfile:
    industry_id: str
    name: str
    description: str
    metadata_schema: MetadataSchema
    document_types: tuple[DocumentTypeDefinition, ...]
    entity_types: tuple[EntityTypeDefinition, ...]
    risk_policy: RiskPolicy
    required_evidence_policy: RequiredEvidencePolicy
    approval_policy: ApprovalPolicy
    acl_mapping_policy: ACLMappingPolicy
    workflow_definitions: tuple[WorkflowDefinition, ...]
    draft_artifact_types: tuple[DraftArtifactTypeDefinition, ...]
    draft_review_policy: DraftReviewPolicy
    kpi_definitions: tuple[KPIDefinition, ...]
    dashboard_widgets: tuple[DashboardWidgetDefinition, ...]
    governance_profile: GovernanceProfile
    audit_event_definitions: tuple[AuditEventDefinition, ...] = ()
    evaluation_profile: EvaluationProfile | None = None
    record_retention_policy: RecordRetentionPolicy | None = None
    regulated_activity_policy: RegulatedActivityPolicy | None = None
    advice_boundary_policy: AdviceBoundaryPolicy | None = None
    disclosure_evidence_policy: DisclosureEvidencePolicy | None = None
    compliance_review_policy: ComplianceReviewPolicy | None = None


class IndustryProfileService:
    def __init__(self, profiles: tuple[IndustryProfile, ...] = ()) -> None:
        self._profiles = {profile.industry_id: profile for profile in profiles}
        self._bindings: dict[tuple[str, str | None], str] = {}

    def register(self, profile: IndustryProfile) -> None:
        self._profiles[profile.industry_id] = profile

    def list_profiles(self) -> tuple[IndustryProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def get(self, industry_id: str) -> IndustryProfile:
        try:
            return self._profiles[industry_id]
        except KeyError as exc:
            raise KeyError(f"unknown industry profile: {industry_id}") from exc

    def bind_profile(
        self, tenant_id: str, industry_id: str, collection_id: str | None = None
    ) -> None:
        self.get(industry_id)
        self._bindings[(tenant_id, collection_id)] = industry_id

    def resolve(
        self, tenant_id: str, collection_id: str | None = None, industry_id: str | None = None
    ) -> IndustryProfile:
        if industry_id is not None:
            return self.get(industry_id)
        for key in ((tenant_id, collection_id), (tenant_id, None)):
            if key in self._bindings:
                return self.get(self._bindings[key])
        if len(self._profiles) == 1:
            return next(iter(self._profiles.values()))
        raise KeyError("no industry profile binding for tenant/collection")


class MetadataSchemaService:
    def __init__(self, schemas: tuple[MetadataSchema, ...] = ()) -> None:
        self._schemas: dict[tuple[str, str, int], MetadataSchema] = {}
        for schema in schemas:
            self.register(schema)

    def register(self, schema: MetadataSchema) -> None:
        for field_def in schema.fields:
            if field_def.field_type not in _FIELD_TYPES:
                raise ValueError(f"unsupported field type {field_def.field_type!r}")
        self._schemas[(schema.industry_id, schema.schema_id, schema.version)] = schema

    def latest(self, industry_id: str, schema_id: str | None = None) -> MetadataSchema:
        matches = [
            schema
            for (ind, sid, _version), schema in self._schemas.items()
            if ind == industry_id and (schema_id is None or sid == schema_id)
        ]
        if not matches:
            raise KeyError(f"no metadata schema for industry={industry_id!r}")
        return max(matches, key=lambda schema: schema.version)

    def validate(
        self,
        industry_id: str,
        metadata: dict,
        *,
        schema_id: str | None = None,
        version: int | None = None,
    ) -> MetadataValidationResult:
        schema = (
            self.latest(industry_id, schema_id)
            if version is None
            else self._schemas[(industry_id, schema_id or industry_id, version)]
        )
        errors: list[str] = []
        field_map = schema.field_map()
        required = set(schema.required_fields) | {
            name for name, definition in field_map.items() if definition.required
        }
        for name in sorted(required):
            if metadata.get(name) in (None, ""):
                errors.append(f"missing required field: {name}")
        for name, value in metadata.items():
            definition = field_map.get(name)
            if definition is None:
                continue
            if not _value_matches_type(value, definition.field_type):
                errors.append(f"field {name} expected {definition.field_type}")
            if definition.allowed_values and str(value) not in definition.allowed_values:
                errors.append(f"field {name} outside allowed values")
        return MetadataValidationResult(valid=not errors, errors=tuple(errors))


class IndustryRiskPolicyService:
    def evaluate(
        self,
        policy: RiskPolicy,
        query: str,
        *,
        metadata: dict | None = None,
        uncertain: bool = False,
    ) -> RiskDecision:
        metadata = metadata or {}
        haystack = query.casefold()
        matched: list[str] = []
        categories: list[str] = []
        confidence = 0.0
        decision = policy.default_action
        for rule in (
            policy.keyword_rules + policy.metadata_rules + policy.intent_classification_rules
        ):
            keyword_hit = any(keyword.casefold() in haystack for keyword in rule.keywords)
            metadata_hit = bool(rule.metadata_matches) and all(
                str(metadata.get(k, "")) == v for k, v in rule.metadata_matches.items()
            )
            if keyword_hit or metadata_hit:
                matched.append(rule.rule_id)
                categories.append(rule.category)
                confidence = max(confidence, rule.confidence)
                decision = _stronger_decision(decision, rule.decision)
        if not matched and uncertain:
            decision = policy.uncertain_case_action
            confidence = 0.5
            categories = ("uncertain",)
            matched = ("uncertain_case_action",)
        return RiskDecision(
            risk_decision_id=f"risk_{uuid4().hex}",
            industry_id=policy.industry_id,
            risk_categories=tuple(dict.fromkeys(categories)),
            matched_rules=tuple(matched),
            confidence=confidence,
            decision=decision,
            reason="matched_rules" if matched else "default_action",
            policy_version=policy.version,
        )


class RequiredEvidencePolicyService:
    def __init__(self, *, today: date | None = None) -> None:
        self.today = today or date.today()

    def check(
        self, policy: RequiredEvidencePolicy, citations: tuple[IndustryCitation, ...]
    ) -> EvidenceDecision:
        valid: list[IndustryCitation] = []
        invalid: list[IndustryCitation] = []
        reasons: list[str] = []
        allowed_types = set(policy.citation_types_allowed)
        for citation in citations:
            if allowed_types and citation.document_type not in allowed_types:
                invalid.append(citation)
                reasons.append(f"citation type not allowed: {citation.document_type}")
                continue
            status = citation.approval_status
            if status == "obsolete" and policy.allow_obsolete_as_reference:
                invalid.append(citation)
                reasons.append("obsolete citation cannot be formal evidence")
                continue
            if status == "draft" and policy.allow_draft_as_reference:
                invalid.append(citation)
                reasons.append("draft citation cannot be formal evidence")
                continue
            if status != policy.required_approval_status:
                invalid.append(citation)
                reasons.append(f"approval status {status} is not {policy.required_approval_status}")
                continue
            if policy.require_effective_date_valid and not _effective_date_valid(
                citation.effective_date, self.today
            ):
                invalid.append(citation)
                reasons.append("effective date missing or invalid")
                continue
            valid.append(citation)
        if len(valid) < policy.minimum_citation_count:
            reasons.append(
                f"minimum citation count not met: {len(valid)}/{policy.minimum_citation_count}"
            )
            return EvidenceDecision(
                passed=False,
                status=policy.insufficient_evidence_behavior,
                valid_citations=tuple(valid),
                invalid_citations=tuple(invalid),
                reasons=tuple(dict.fromkeys(reasons)),
            )
        return EvidenceDecision(passed=True, status="ok", valid_citations=tuple(valid))


class DraftArtifactService:
    def __init__(self, audit: Callable[[FrameworkAuditEvent], None] | None = None) -> None:
        self._artifacts: dict[str, FrameworkDraftArtifact] = {}
        self._audit_events: list[FrameworkAuditEvent] = []
        self._audit = audit

    def create(
        self,
        profile: IndustryProfile,
        artifact_type: str,
        *,
        source_citations: tuple[IndustryCitation, ...] = (),
        source_document_ids: tuple[str, ...] = (),
        payload: dict | None = None,
        template_id: str | None = None,
        tenant_id: str = "",
        actor_id: str = "ai",
        reviewer_id: str | None = None,
        reviewer_group: str | None = None,
    ) -> FrameworkDraftArtifact:
        definition = _draft_type(profile, artifact_type)
        if len(source_citations) < definition.required_citations:
            raise ValueError("draft artifact requires source citations")
        artifact = FrameworkDraftArtifact(
            artifact_id=f"draft_{uuid4().hex}",
            industry_id=profile.industry_id,
            artifact_type=artifact_type,
            source_citations=tuple(source_citations),
            source_document_ids=tuple(source_document_ids),
            template_id=template_id,
            reviewer_id=reviewer_id,
            reviewer_group=reviewer_group,
            payload=dict(payload or {}),
        )
        self._artifacts[artifact.artifact_id] = artifact
        self._emit_audit(
            profile,
            artifact,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="draft.generated",
            decision=artifact.status,
        )
        if reviewer_id or reviewer_group:
            self._emit_audit(
                profile,
                artifact,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="draft.assigned",
                decision=artifact.status,
                metadata={"reviewer_id": reviewer_id, "reviewer_group": reviewer_group},
            )
        return artifact

    def get(self, artifact_id: str) -> FrameworkDraftArtifact | None:
        return self._artifacts.get(artifact_id)

    def list_artifacts(
        self, profile: IndustryProfile | None = None
    ) -> tuple[FrameworkDraftArtifact, ...]:
        artifacts = tuple(self._artifacts[key] for key in sorted(self._artifacts))
        if profile is None:
            return artifacts
        return tuple(
            artifact for artifact in artifacts if artifact.industry_id == profile.industry_id
        )

    def audit_events(self) -> tuple[FrameworkAuditEvent, ...]:
        return tuple(self._audit_events)

    def transition(
        self,
        profile: IndustryProfile,
        artifact_id: str,
        *,
        to_status: str,
        reviewer_id: str | None = None,
        reviewer_role: str | None = None,
        tenant_id: str = "",
        actor_id: str = "",
    ) -> FrameworkDraftArtifact:
        artifact = self._artifacts[artifact_id]
        definition = _draft_type(profile, artifact.artifact_type)
        if to_status == "approved" and artifact.created_by == "ai" and reviewer_id is None:
            raise PermissionError("AI-created draft cannot self-approve")
        if to_status == "approved" and not definition.auto_approve_allowed and reviewer_id is None:
            raise PermissionError("approval requires reviewer")
        if (
            reviewer_role is not None
            and reviewer_role not in profile.draft_review_policy.reviewer_roles
        ):
            raise PermissionError("reviewer role is not allowed")
        transition = (artifact.status, to_status)
        if transition not in profile.draft_review_policy.allowed_transitions:
            raise ValueError(f"transition not allowed: {artifact.status}->{to_status}")
        updated = FrameworkDraftArtifact(
            artifact_id=artifact.artifact_id,
            industry_id=artifact.industry_id,
            artifact_type=artifact.artifact_type,
            status=to_status,
            created_by=artifact.created_by,
            reviewer_id=reviewer_id or artifact.reviewer_id,
            reviewer_group=artifact.reviewer_group,
            source_citations=artifact.source_citations,
            source_document_ids=artifact.source_document_ids,
            generated_at=artifact.generated_at,
            template_id=artifact.template_id,
            audit_log_ref=artifact.audit_log_ref,
            payload=artifact.payload,
        )
        self._artifacts[artifact_id] = updated
        if reviewer_id and reviewer_id != artifact.reviewer_id:
            self._emit_audit(
                profile,
                updated,
                tenant_id=tenant_id,
                actor_id=actor_id or reviewer_id,
                action="draft.assigned",
                decision=to_status,
                metadata={"reviewer_id": reviewer_id, "reviewer_role": reviewer_role},
            )
        self._emit_audit(
            profile,
            updated,
            tenant_id=tenant_id,
            actor_id=actor_id or reviewer_id or "",
            action="draft.review_transition",
            decision=to_status,
            metadata={"from_status": artifact.status, "to_status": to_status},
        )
        if to_status == "archived":
            self._emit_audit(
                profile,
                updated,
                tenant_id=tenant_id,
                actor_id=actor_id or reviewer_id or "",
                action="draft.archived",
                decision=to_status,
            )
        return updated

    def _emit_audit(
        self,
        profile: IndustryProfile,
        artifact: FrameworkDraftArtifact,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        decision: str,
        metadata: dict | None = None,
    ) -> None:
        event = FrameworkAuditEvent(
            tenant_id=tenant_id,
            industry_id=profile.industry_id,
            workflow_id="draft",
            action=action,
            decision=decision,
            actor_id=actor_id,
            metadata={
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                **dict(metadata or {}),
            },
        )
        self._audit_events.append(event)
        if self._audit is not None:
            self._audit(event)


class IndustryWorkflowService:
    """Generic 010 workflow runner with 001-compatible service hooks.

    The service does not own retrieval, generation, audit, or cost persistence. Instead, production
    composition injects the 001 services through ``IndustryWorkflowHooks``. The runner guarantees the
    sequencing and policy gates: profile/schema resolution, retrieval, risk decision, evidence check,
    citation access, answer or draft creation, audit, and cost events.
    """

    def __init__(
        self,
        profile_service: IndustryProfileService | None = None,
        *,
        risk_service: IndustryRiskPolicyService | None = None,
        evidence_service: RequiredEvidencePolicyService | None = None,
        draft_service: DraftArtifactService | None = None,
        hooks: IndustryWorkflowHooks | None = None,
    ) -> None:
        self.profile_service = profile_service or create_default_profile_service()
        self.risk_service = risk_service or IndustryRiskPolicyService()
        self.evidence_service = evidence_service or RequiredEvidencePolicyService()
        self.draft_service = draft_service or DraftArtifactService()
        self.hooks = hooks or IndustryWorkflowHooks()
        self._audit_events: list[FrameworkAuditEvent] = []
        self._cost_events: list[FrameworkCostEvent] = []

    def run(self, request: WorkflowRequest) -> WorkflowResult:
        self._audit_events = []
        self._cost_events = []
        profile = self.profile_service.resolve(
            request.tenant_id, collection_id=request.collection_id, industry_id=request.industry_id
        )
        workflow = _workflow(profile, request.workflow_id)
        validation = MetadataSchemaService((profile.metadata_schema,)).validate(
            profile.industry_id, _metadata_for_validation(request)
        )
        if not validation.valid:
            risk = self.risk_service.evaluate(
                profile.risk_policy,
                request.query,
                metadata=request.metadata,
                uncertain=request.uncertain,
            )
            evidence = EvidenceDecision(
                passed=False,
                status="validation_error",
                reasons=validation.errors,
            )
            self._emit_audit(
                request,
                profile,
                workflow,
                action="workflow.validation",
                decision="validation_error",
                metadata={"errors": validation.errors},
            )
            return WorkflowResult(
                status="validation_error",
                text="workflow input metadata failed validation",
                profile=profile,
                workflow=workflow,
                risk_decision=risk,
                evidence_decision=evidence,
                audit_events=tuple(self._audit_events),
                cost_events=tuple(self._cost_events),
                review_required=True,
                blocked=True,
            )

        self._emit_audit(request, profile, workflow, action="workflow.started", decision="started")
        citations = self._retrieve(request, profile, workflow)
        self._emit_cost(
            request,
            profile,
            workflow,
            kind="retrieval",
            metadata={"citation_count": len(citations)},
        )

        risk = self.risk_service.evaluate(
            profile.risk_policy,
            request.query,
            metadata=request.metadata,
            uncertain=request.uncertain,
        )
        self._emit_audit(
            request,
            profile,
            workflow,
            action="risk.decision",
            decision=risk.decision,
            metadata={
                "risk_decision_id": risk.risk_decision_id,
                "categories": risk.risk_categories,
                "matched_rules": risk.matched_rules,
            },
        )

        evidence = self.evidence_service.check(profile.required_evidence_policy, citations)
        self._emit_audit(
            request,
            profile,
            workflow,
            action="evidence.decision",
            decision=evidence.status,
            metadata={
                "passed": evidence.passed,
                "valid_citation_count": len(evidence.valid_citations),
                "reasons": evidence.reasons,
            },
        )
        if not evidence.passed and (risk.high_risk or workflow.review_required):
            self._emit_audit(
                request,
                profile,
                workflow,
                action="workflow.completed",
                decision=evidence.status,
            )
            return WorkflowResult(
                status=evidence.status,
                text="approved and effective evidence is insufficient for a definitive response",
                profile=profile,
                workflow=workflow,
                risk_decision=risk,
                evidence_decision=evidence,
                citations=evidence.valid_citations,
                audit_events=tuple(self._audit_events),
                cost_events=tuple(self._cost_events),
                review_required=True,
                blocked=True,
            )

        if self.hooks.citation_access is not None:
            self.hooks.citation_access(request, profile, workflow, evidence.valid_citations)
        self._emit_audit(
            request,
            profile,
            workflow,
            action="citation.access",
            decision="accessed",
            metadata={"citation_ids": tuple(c.document_id for c in evidence.valid_citations)},
        )

        draft_type = request.draft_artifact_type or workflow.draft_artifact_type
        if draft_type:
            draft = self.draft_service.create(
                profile,
                draft_type,
                source_citations=evidence.valid_citations,
                source_document_ids=_source_document_ids(request, evidence.valid_citations),
                payload=request.payload,
            )
            self._emit_cost(request, profile, workflow, kind="draft")
            self._emit_audit(
                request,
                profile,
                workflow,
                action="workflow.completed",
                decision="draft",
                metadata={"artifact_id": draft.artifact_id, "artifact_type": draft.artifact_type},
            )
            return WorkflowResult(
                status="draft",
                text="draft artifact created",
                profile=profile,
                workflow=workflow,
                risk_decision=risk,
                evidence_decision=evidence,
                citations=evidence.valid_citations,
                draft_artifact=draft,
                audit_events=tuple(self._audit_events),
                cost_events=tuple(self._cost_events),
                review_required=True,
            )

        text = self._answer(request, profile, workflow, evidence.valid_citations)
        self._emit_cost(request, profile, workflow, kind="answer")
        self._emit_audit(
            request,
            profile,
            workflow,
            action="workflow.completed",
            decision="ok",
        )
        return WorkflowResult(
            status="ok",
            text=text,
            profile=profile,
            workflow=workflow,
            risk_decision=risk,
            evidence_decision=evidence,
            citations=evidence.valid_citations,
            audit_events=tuple(self._audit_events),
            cost_events=tuple(self._cost_events),
            review_required=workflow.review_required or risk.high_risk,
        )

    def _retrieve(
        self, request: WorkflowRequest, profile: IndustryProfile, workflow: WorkflowDefinition
    ) -> tuple[IndustryCitation, ...]:
        if self.hooks.retrieve is not None:
            return tuple(self.hooks.retrieve(request, profile, workflow))
        return tuple(request.citations)

    def _answer(
        self,
        request: WorkflowRequest,
        profile: IndustryProfile,
        workflow: WorkflowDefinition,
        citations: tuple[IndustryCitation, ...],
    ) -> str:
        if self.hooks.answer is not None:
            return self.hooks.answer(request, profile, workflow, citations)
        cited = ", ".join(citation.document_id for citation in citations)
        return f"workflow completed with approved evidence: {cited}"

    def _emit_audit(
        self,
        request: WorkflowRequest,
        profile: IndustryProfile,
        workflow: WorkflowDefinition,
        *,
        action: str,
        decision: str,
        metadata: dict | None = None,
    ) -> None:
        event = FrameworkAuditEvent(
            tenant_id=request.tenant_id,
            industry_id=profile.industry_id,
            workflow_id=workflow.workflow_id,
            action=action,
            decision=decision,
            actor_id=request.actor_id,
            metadata=dict(metadata or {}),
        )
        self._audit_events.append(event)
        if self.hooks.audit is not None:
            self.hooks.audit(event)

    def _emit_cost(
        self,
        request: WorkflowRequest,
        profile: IndustryProfile,
        workflow: WorkflowDefinition,
        *,
        kind: str,
        units: int = 1,
        metadata: dict | None = None,
    ) -> None:
        event = FrameworkCostEvent(
            tenant_id=request.tenant_id,
            industry_id=profile.industry_id,
            workflow_id=workflow.workflow_id,
            kind=kind,
            units=units,
            metadata=dict(metadata or {}),
        )
        self._cost_events.append(event)
        if self.hooks.cost is not None:
            self.hooks.cost(event)


class IndustryKPIService:
    def calculate(
        self,
        profile: IndustryProfile,
        *,
        tenant_id: str = "",
        audit_events: tuple[FrameworkAuditEvent, ...] = (),
        draft_artifacts: tuple[FrameworkDraftArtifact, ...] = (),
        feedback_events: tuple[dict, ...] = (),
        evaluation_results: tuple[dict, ...] = (),
    ) -> tuple[KPIValue, ...]:
        values: list[KPIValue] = []
        for definition in profile.kpi_definitions:
            source_count = 0
            if "audit" in definition.event_sources:
                source_count += sum(
                    1
                    for event in audit_events
                    if _event_matches(event, tenant_id, profile.industry_id)
                )
            if "draft" in definition.event_sources:
                source_count += sum(
                    1 for artifact in draft_artifacts if artifact.industry_id == profile.industry_id
                )
            if "feedback" in definition.event_sources:
                source_count += sum(
                    1
                    for event in feedback_events
                    if _dict_event_matches(event, tenant_id, profile.industry_id)
                )
            if "evaluation" in definition.event_sources:
                source_count += sum(
                    1
                    for result in evaluation_results
                    if _dict_event_matches(result, tenant_id, profile.industry_id)
                )
            value = (
                _ratio_value(source_count) if "rate" in definition.kpi_id else float(source_count)
            )
            values.append(
                KPIValue(
                    kpi_id=definition.kpi_id,
                    industry_id=profile.industry_id,
                    tenant_id=tenant_id,
                    value=value,
                    source_event_count=source_count,
                    dimensions={"formula": definition.formula},
                )
            )
        return tuple(values)


class IndustryDashboardService:
    def render(
        self,
        profile: IndustryProfile,
        *,
        tenant_id: str,
        roles: tuple[str, ...] = (),
        kpi_values: tuple[KPIValue, ...] = (),
        allowed_industry_ids: tuple[str, ...] | None = None,
    ) -> DashboardResult:
        allowed_industries = set(allowed_industry_ids or (profile.industry_id,))
        visible_kpis = tuple(
            value
            for value in kpi_values
            if value.industry_id == profile.industry_id
            and (not value.tenant_id or value.tenant_id == tenant_id)
        )
        denied: list[str] = []
        widgets: list[dict] = []
        for widget in profile.dashboard_widgets:
            if profile.industry_id not in allowed_industries or not _role_allowed(
                widget.required_role, roles
            ):
                denied.append(widget.widget_id)
                continue
            widget_kpis = tuple(value for value in visible_kpis if value.kpi_id in widget.kpi_ids)
            widgets.append(
                {
                    "widget_id": widget.widget_id,
                    "industry_id": widget.industry_id,
                    "name": widget.name,
                    "required_role": widget.required_role,
                    "kpis": tuple(_kpi_value_json(value) for value in widget_kpis),
                    "filters": dict(widget.filters),
                }
            )
        return DashboardResult(
            tenant_id=tenant_id,
            industry_id=profile.industry_id,
            widgets=tuple(widgets),
            kpis=visible_kpis,
            denied_widget_ids=tuple(denied),
        )


class IndustryGovernanceStatusService:
    def status(
        self,
        profile: IndustryProfile,
        *,
        provider_facts: dict | None = None,
        audit_facts: dict | None = None,
        no_train_facts: dict | None = None,
        retention_facts: dict | None = None,
    ) -> GovernanceStatus:
        provider_facts = provider_facts or {}
        audit_facts = audit_facts or {}
        no_train_facts = no_train_facts or {}
        retention_facts = retention_facts or {}
        no_train_enforced = bool(no_train_facts.get("enforced", True)) and bool(
            profile.governance_profile.no_train_policy_ref
        )
        audit_ready = bool(audit_facts.get("audit_sink_ready", True)) and bool(
            profile.audit_event_definitions
        )
        provider_ready = bool(provider_facts.get("no_train_required", True)) and bool(
            provider_facts.get("zero_retention_required", True)
        )
        retention_ready = profile.record_retention_policy is not None and bool(
            retention_facts.get("retention_controls_ready", True)
        )
        ready = no_train_enforced and audit_ready and provider_ready and retention_ready
        return GovernanceStatus(
            industry_id=profile.industry_id,
            status="ready" if ready else "action_required",
            no_train_enforced=no_train_enforced,
            audit_ready=audit_ready,
            provider_ready=provider_ready,
            retention_ready=retention_ready,
            facts={
                "provider": dict(provider_facts),
                "audit": dict(audit_facts),
                "no_train": dict(no_train_facts),
                "retention": dict(retention_facts),
                "governance_profile_id": profile.governance_profile.governance_profile_id,
            },
        )


class RecordRetentionPolicyService:
    def __init__(self, *, today: date | None = None) -> None:
        self.today = today or date.today()

    def decide(
        self,
        policy: RecordRetentionPolicy,
        *,
        document_id: str,
        effective_date: str | None = None,
        legal_hold: bool = False,
    ) -> RetentionDecision:
        base_date = self.today
        if effective_date:
            try:
                base_date = date.fromisoformat(effective_date)
            except ValueError:
                base_date = self.today
        retain_until = date.fromordinal(base_date.toordinal() + policy.retention_days).isoformat()
        return RetentionDecision(
            document_id=document_id,
            industry_id=policy.industry_id,
            retention_policy_ref=policy.policy_id,
            retain_until=retain_until,
            export_allowed=policy.export_supported,
            delete_allowed=policy.delete_supported and not legal_hold,
            audit_required=policy.audit_required,
        )


def create_default_profile_service() -> IndustryProfileService:
    return IndustryProfileService(seed_industry_profiles())


def seed_industry_profiles() -> tuple[IndustryProfile, ...]:
    return (
        _manufacturing_profile(),
        _real_estate_profile(),
        _investment_profile(),
    )


def _base_fields(*field_names: str) -> tuple[MetadataFieldDefinition, ...]:
    fields = [
        MetadataFieldDefinition(name, name, required=name in COMMON_METADATA_FIELDS)
        for name in COMMON_METADATA_FIELDS
    ]
    fields.extend(
        MetadataFieldDefinition(name, name, searchable=True, filterable=True)
        for name in field_names
    )
    return tuple(fields)


def _schema(industry_id: str, fields: tuple[MetadataFieldDefinition, ...]) -> MetadataSchema:
    required = tuple(field.field_name for field in fields if field.required)
    indexed = tuple(field.field_name for field in fields if field.filterable or field.facetable)
    pii = tuple(field.field_name for field in fields if field.pii_category)
    return MetadataSchema(
        schema_id=f"{industry_id}_metadata",
        industry_id=industry_id,
        version=1,
        fields=fields,
        required_fields=required,
        indexed_fields=indexed,
        pii_fields=pii,
    )


def _manufacturing_profile() -> IndustryProfile:
    industry_id = "manufacturing"
    fields = _base_fields(
        "factory_id",
        "line_id",
        "process_id",
        "equipment_id",
        "alarm_code",
        "product_id",
        "part_number",
        "defect_type",
        "failure_mode",
    )
    return _profile(
        industry_id=industry_id,
        name="Manufacturing",
        description="Manufacturing field knowledge RAG profile",
        schema=_schema(industry_id, fields),
        document_types=("work_instruction", "inspection", "quality_report", "trouble_report"),
        entity_types=("factory", "equipment", "process", "part"),
        workflows=("trouble_investigation", "similar_quality_issues", "checklist_draft"),
        draft_types=("maintenance_checklist", "trouble_report", "quality_report", "faq"),
        kpis=("self_resolution_rate", "high_risk_query_count", "safety_gate_block_count"),
        risk_categories=("dangerous_work", "equipment_operation", "quality_judgment"),
        risk_rules=(
            KeywordRiskRule(
                "mfg_dangerous_work", "dangerous_work", ("disassemble", "高圧", "感電", "分解")
            ),
            KeywordRiskRule("mfg_quality", "quality_judgment", ("shipment", "出荷", "defect")),
        ),
        acl_fields=("factory_id", "department", "role", "equipment_id"),
    )


def _real_estate_profile() -> IndustryProfile:
    industry_id = "real_estate_pm"
    fields = _base_fields(
        "property_id",
        "building_id",
        "unit_id",
        "lease_contract_id",
        "owner_id",
        "occupant_id",
        "repair_category",
        "personal_data_category",
    )
    return _profile(
        industry_id=industry_id,
        name="Real Estate Property Management",
        description="Property-management RAG profile",
        schema=_schema(industry_id, fields),
        document_types=("lease_contract", "management_rule", "repair_history", "invoice"),
        entity_types=("property", "building", "unit", "owner", "occupant"),
        workflows=(
            "contract_question",
            "repair_investigation",
            "occupant_reply_draft",
            "owner_report_draft",
        ),
        draft_types=("occupant_reply", "owner_report", "repair_report", "move_out_checklist"),
        kpis=("repair_case_lookup_count", "owner_report_draft_count", "risk_gate_block_count"),
        risk_categories=(
            "contract_condition",
            "cost_responsibility",
            "legal_risk",
            "personal_data",
        ),
        risk_rules=(
            KeywordRiskRule("re_contract", "contract_condition", ("契約", "ペット", "管理規約")),
            KeywordRiskRule(
                "re_restoration", "cost_responsibility", ("原状回復", "費用負担", "請求")
            ),
            KeywordRiskRule("re_personal_data", "personal_data", ("保証人", "支払い", "電話番号")),
            KeywordRiskRule("re_legal", "legal_risk", ("法的", "違法", "問題ない")),
        ),
        acl_fields=("property_id", "building_id", "unit_id", "owner_id", "personal_data_category"),
    )


def _investment_profile() -> IndustryProfile:
    industry_id = "investment_management"
    fields = _base_fields(
        "fund_id",
        "share_class_id",
        "asset_class",
        "strategy",
        "distribution_partner_id",
        "regulated_activity_category",
        "confidential_data_category",
        "personal_data_category",
    )
    profile = _profile(
        industry_id=industry_id,
        name="Investment Management",
        description="Investment-management and mutual-fund RAG profile",
        schema=_schema(industry_id, fields),
        document_types=("prospectus", "monthly_report", "marketing_material", "compliance_rule"),
        entity_types=("fund", "share_class", "distribution_partner", "strategy"),
        workflows=(
            "fund_question",
            "rfp_response_draft",
            "ddq_response_draft",
            "marketing_material_check",
            "monthly_commentary_draft",
            "compliance_rule_question",
        ),
        draft_types=(
            "rfp_response",
            "ddq_response",
            "marketing_material_comment",
            "monthly_commentary",
        ),
        kpis=(
            "regulated_query_count",
            "advice_boundary_trigger_count",
            "compliance_review_pending_count",
        ),
        risk_categories=("advice_boundary", "regulated_activity", "disclosure_evidence"),
        risk_rules=(
            KeywordRiskRule(
                "im_advice", "advice_boundary", ("買うべき", "買わせる", "売るべき", "適合性")
            ),
            KeywordRiskRule(
                "im_disclosure", "disclosure_evidence", ("過去実績", "将来成果", "広告")
            ),
            KeywordRiskRule("im_regulated", "regulated_activity", ("投資助言", "勧誘", "販売資料")),
        ),
        acl_fields=("fund_id", "role", "confidential_data_category", "regulated_activity_category"),
        regulated=True,
    )
    return profile


def _profile(
    *,
    industry_id: str,
    name: str,
    description: str,
    schema: MetadataSchema,
    document_types: tuple[str, ...],
    entity_types: tuple[str, ...],
    workflows: tuple[str, ...],
    draft_types: tuple[str, ...],
    kpis: tuple[str, ...],
    risk_categories: tuple[str, ...],
    risk_rules: tuple[KeywordRiskRule, ...],
    acl_fields: tuple[str, ...],
    regulated: bool = False,
) -> IndustryProfile:
    document_defs = tuple(
        DocumentTypeDefinition(
            document_type=doc_type, industry_id=industry_id, display_name=doc_type
        )
        for doc_type in document_types
    )
    entity_defs = tuple(
        EntityTypeDefinition(
            entity_type=entity,
            industry_id=industry_id,
            display_name=entity,
            id_field=f"{entity}_id",
            label_field="name",
        )
        for entity in entity_types
    )
    workflow_defs = tuple(
        WorkflowDefinition(
            workflow_id=workflow,
            industry_id=industry_id,
            name=workflow,
            risk_policy_id=f"{industry_id}_risk",
            required_evidence_policy_id=f"{industry_id}_evidence",
            draft_artifact_type=_artifact_type_for_workflow(workflow),
            review_required=True,
            audit_events=(f"{industry_id}.{workflow}",),
            kpi_events=(workflow,),
        )
        for workflow in workflows
    )
    draft_defs = tuple(
        DraftArtifactTypeDefinition(
            artifact_type=artifact_type,
            industry_id=industry_id,
            display_name=artifact_type,
            required_citations=1,
            review_required=True,
            auto_approve_allowed=False,
        )
        for artifact_type in draft_types
    )
    kpi_defs = tuple(
        KPIDefinition(
            kpi_id=kpi,
            industry_id=industry_id,
            name=kpi,
            description=f"{kpi} derived from audit and workflow events",
            formula="count_or_ratio_from_audit",
            event_sources=("audit", "draft", "evaluation"),
        )
        for kpi in kpis
    )
    widgets = (
        DashboardWidgetDefinition(
            widget_id=f"{industry_id}_overview",
            industry_id=industry_id,
            name="Overview",
            kpi_ids=tuple(kpis),
        ),
    )
    compliance_policy = None
    disclosure_policy = None
    advice_policy = None
    regulated_policy = None
    if regulated:
        regulated_policy = RegulatedActivityPolicy(
            policy_id=f"{industry_id}_regulated_activity",
            industry_id=industry_id,
            regulated_activity_categories=risk_categories,
        )
        advice_policy = AdviceBoundaryPolicy(
            policy_id=f"{industry_id}_advice_boundary",
            industry_id=industry_id,
            advice_like_intent_categories=("buy_sell_recommendation", "suitability_judgment"),
        )
        disclosure_policy = DisclosureEvidencePolicy(
            policy_id=f"{industry_id}_disclosure",
            industry_id=industry_id,
            required_source_document_types=("prospectus", "monthly_report", "compliance_rule"),
        )
        compliance_policy = ComplianceReviewPolicy(
            policy_id=f"{industry_id}_compliance_review",
            industry_id=industry_id,
            review_required_artifact_types=draft_types,
        )
    return IndustryProfile(
        industry_id=industry_id,
        name=name,
        description=description,
        metadata_schema=schema,
        document_types=document_defs,
        entity_types=entity_defs,
        risk_policy=RiskPolicy(
            risk_policy_id=f"{industry_id}_risk",
            industry_id=industry_id,
            risk_categories=risk_categories,
            keyword_rules=risk_rules,
            default_action="allow",
            uncertain_case_action="review_required",
        ),
        required_evidence_policy=RequiredEvidencePolicy(
            policy_id=f"{industry_id}_evidence",
            industry_id=industry_id,
            required_approval_status="approved",
            require_effective_date_valid=True,
            minimum_citation_count=1,
            insufficient_evidence_behavior="insufficient_evidence",
        ),
        approval_policy=ApprovalPolicy(
            policy_id=f"{industry_id}_approval", industry_id=industry_id
        ),
        acl_mapping_policy=ACLMappingPolicy(
            policy_id=f"{industry_id}_acl",
            industry_id=industry_id,
            metadata_fields_to_acl=acl_fields,
        ),
        workflow_definitions=workflow_defs,
        draft_artifact_types=draft_defs,
        draft_review_policy=DraftReviewPolicy(
            policy_id=f"{industry_id}_draft_review", industry_id=industry_id
        ),
        kpi_definitions=kpi_defs,
        dashboard_widgets=widgets,
        governance_profile=GovernanceProfile(
            governance_profile_id=f"{industry_id}_governance",
            industry_id=industry_id,
            audit_event_definitions=tuple(f"{industry_id}.{workflow}" for workflow in workflows),
        ),
        audit_event_definitions=tuple(
            AuditEventDefinition(event_type=f"{industry_id}.{workflow}", industry_id=industry_id)
            for workflow in workflows
        ),
        evaluation_profile=EvaluationProfile(
            profile_id=f"{industry_id}_evaluation", industry_id=industry_id
        ),
        record_retention_policy=RecordRetentionPolicy(
            policy_id=f"{industry_id}_retention",
            industry_id=industry_id,
        ),
        regulated_activity_policy=regulated_policy,
        advice_boundary_policy=advice_policy,
        disclosure_evidence_policy=disclosure_policy,
        compliance_review_policy=compliance_policy,
    )


def _value_matches_type(value: object, field_type: str) -> bool:
    if field_type == "string":
        return isinstance(value, str)
    if field_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "array":
        return isinstance(value, (list, tuple))
    if field_type == "object":
        return isinstance(value, dict)
    return False


def _stronger_decision(current: str, candidate: str) -> str:
    order = {"allow": 0, "review_required": 1, "insufficient_evidence": 2, "blocked": 3}
    return candidate if order.get(candidate, 0) > order.get(current, 0) else current


def _effective_date_valid(value: str | None, today: date) -> bool:
    if not value:
        return False
    try:
        return date.fromisoformat(value) <= today
    except ValueError:
        return False


def _draft_type(profile: IndustryProfile, artifact_type: str) -> DraftArtifactTypeDefinition:
    for definition in profile.draft_artifact_types:
        if definition.artifact_type == artifact_type:
            return definition
    raise KeyError(f"unknown draft artifact type: {artifact_type}")


def _workflow(profile: IndustryProfile, workflow_id: str) -> WorkflowDefinition:
    for workflow in profile.workflow_definitions:
        if workflow.workflow_id == workflow_id:
            return workflow
    raise KeyError(f"unknown workflow: {workflow_id}")


def _metadata_for_validation(request: WorkflowRequest) -> dict:
    metadata = dict(request.metadata)
    metadata.setdefault("tenant_id", request.tenant_id)
    metadata.setdefault("collection_id", request.collection_id or "default")
    metadata.setdefault("document_id", f"workflow:{request.workflow_id}")
    metadata.setdefault("approval_status", "approved")
    metadata.setdefault("effective_date", date.today().isoformat())
    metadata.setdefault("access_scope", "tenant")
    metadata.setdefault("acl_tags", "tenant")
    metadata.setdefault("no_train_policy_ref", "default_no_train")
    metadata.setdefault("retention_policy_ref", "default_retention")
    return metadata


def _source_document_ids(
    request: WorkflowRequest, citations: tuple[IndustryCitation, ...]
) -> tuple[str, ...]:
    if request.source_document_ids:
        return tuple(request.source_document_ids)
    return tuple(dict.fromkeys(citation.document_id for citation in citations))


def _artifact_type_for_workflow(workflow_id: str) -> str | None:
    if workflow_id == "checklist_draft":
        return "maintenance_checklist"
    if workflow_id.endswith("_draft"):
        return workflow_id.removesuffix("_draft")
    return None


def _event_matches(event: FrameworkAuditEvent, tenant_id: str, industry_id: str) -> bool:
    return event.industry_id == industry_id and (not tenant_id or event.tenant_id == tenant_id)


def _dict_event_matches(event: dict, tenant_id: str, industry_id: str) -> bool:
    event_industry = event.get("industry_id")
    event_tenant = event.get("tenant_id")
    return (event_industry in (None, industry_id)) and (
        not tenant_id or event_tenant in (None, tenant_id)
    )


def _ratio_value(source_count: int) -> float:
    return 1.0 if source_count else 0.0


def _role_allowed(required_role: str, roles: tuple[str, ...]) -> bool:
    return required_role in roles or "admin" in roles


def _kpi_value_json(value: KPIValue) -> dict:
    return {
        "kpi_id": value.kpi_id,
        "industry_id": value.industry_id,
        "tenant_id": value.tenant_id,
        "value": value.value,
        "source_event_count": value.source_event_count,
        "dimensions": dict(value.dimensions),
    }
