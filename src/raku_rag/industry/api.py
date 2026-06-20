"""Generic 010 industry API runtime.

The NestJS facade and contract tests use this deterministic service as the local implementation of
the `/industries/...` contract. Production can bind the same methods to persistent repositories.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from raku_rag.industry.common import IndustryCitation
from raku_rag.industry.framework import (
    DashboardResult,
    DraftArtifactService,
    EvidenceDecision,
    FrameworkAuditEvent,
    FrameworkCostEvent,
    FrameworkDraftArtifact,
    GovernanceStatus,
    IndustryDashboardService,
    IndustryGovernanceStatusService,
    IndustryKPIService,
    IndustryProfile,
    IndustryProfileService,
    IndustryWorkflowService,
    KPIValue,
    MetadataSchemaService,
    RecordRetentionPolicyService,
    RequiredEvidencePolicyService,
    RetentionDecision,
    WorkflowRequest,
    WorkflowResult,
    create_default_profile_service,
)


class IndustryApiService:
    def __init__(
        self,
        profile_service: IndustryProfileService | None = None,
        *,
        draft_service: DraftArtifactService | None = None,
        workflow_service: IndustryWorkflowService | None = None,
        kpi_service: IndustryKPIService | None = None,
        dashboard_service: IndustryDashboardService | None = None,
        governance_service: IndustryGovernanceStatusService | None = None,
        retention_service: RecordRetentionPolicyService | None = None,
    ) -> None:
        self.profile_service = profile_service or create_default_profile_service()
        self.draft_service = draft_service or DraftArtifactService()
        self.workflow_service = workflow_service or IndustryWorkflowService(
            self.profile_service,
            evidence_service=RequiredEvidencePolicyService(),
            draft_service=self.draft_service,
        )
        self.kpi_service = kpi_service or IndustryKPIService()
        self.dashboard_service = dashboard_service or IndustryDashboardService()
        self.governance_service = governance_service or IndustryGovernanceStatusService()
        self.retention_service = retention_service or RecordRetentionPolicyService()

    def list_industries(self, *, tenant_id: str) -> dict:
        return {
            "tenant_id": tenant_id,
            "industries": [
                {
                    "industry_id": profile.industry_id,
                    "name": profile.name,
                    "status": "active",
                    "version": profile.metadata_schema.version,
                }
                for profile in self.profile_service.list_profiles()
            ],
        }

    def profile(self, industry_id: str) -> dict:
        return _profile_json(self.profile_service.get(industry_id))

    def validate_metadata(self, industry_id: str, body: dict) -> dict:
        profile = self.profile_service.get(industry_id)
        metadata = _dict(body.get("metadata") if "metadata" in body else body)
        result = MetadataSchemaService((profile.metadata_schema,)).validate(
            profile.industry_id, metadata
        )
        return {
            "industry_id": profile.industry_id,
            "schema_id": profile.metadata_schema.schema_id,
            "version": profile.metadata_schema.version,
            "valid": result.valid,
            "errors": list(result.errors),
        }

    def enrich_document(self, tenant_id: str, industry_id: str, body: dict) -> dict:
        profile = self.profile_service.get(industry_id)
        document_id = str(body.get("document_id") or f"{industry_id}:document")
        collection_id = str(body.get("collection_id") or "default")
        metadata = {
            **_dict(body.get("metadata")),
            "tenant_id": tenant_id,
            "collection_id": collection_id,
            "document_id": document_id,
            "approval_status": str(body.get("approval_status") or "approved"),
            "effective_date": str(body.get("effective_date") or date.today().isoformat()),
            "access_scope": str(body.get("access_scope") or "tenant"),
            "acl_tags": str(body.get("acl_tags") or "tenant"),
            "no_train_policy_ref": profile.governance_profile.no_train_policy_ref,
            "retention_policy_ref": (
                profile.record_retention_policy.policy_id
                if profile.record_retention_policy is not None
                else "default_retention"
            ),
        }
        result = MetadataSchemaService((profile.metadata_schema,)).validate(
            profile.industry_id, metadata
        )
        retention = (
            self.retention_service.decide(
                profile.record_retention_policy,
                document_id=document_id,
                effective_date=metadata["effective_date"],
                legal_hold=bool(body.get("legal_hold")),
            )
            if profile.record_retention_policy is not None
            else None
        )
        return {
            "industry_id": profile.industry_id,
            "document_id": document_id,
            "document_type": str(body.get("document_type") or ""),
            "metadata": metadata,
            "indexed_fields": list(profile.metadata_schema.indexed_fields),
            "validation": {"valid": result.valid, "errors": list(result.errors)},
            "retention_decision": _retention_decision_json(retention) if retention else None,
        }

    def run_workflow(
        self, tenant_id: str, actor_id: str, industry_id: str, workflow_id: str, body: dict
    ) -> dict:
        result = self.workflow_service.run(
            WorkflowRequest(
                tenant_id=tenant_id,
                industry_id=industry_id,
                workflow_id=workflow_id,
                query=str(body.get("query") or ""),
                collection_id=_optional_str(body.get("collection_id")),
                actor_id=actor_id,
                metadata=_dict(body.get("metadata")),
                citations=_citations(body),
                source_document_ids=tuple(str(v) for v in body.get("source_document_ids") or ()),
                draft_artifact_type=_optional_str(body.get("draft_artifact_type")),
                payload=_dict(body.get("payload")),
                uncertain=bool(body.get("uncertain")),
            )
        )
        return _workflow_result_json(result)

    def create_draft(
        self, tenant_id: str, actor_id: str, industry_id: str, artifact_type: str, body: dict
    ) -> dict:
        profile = self.profile_service.get(industry_id)
        artifact = self.draft_service.create(
            profile,
            artifact_type,
            source_citations=_citations(body),
            source_document_ids=tuple(str(v) for v in body.get("source_document_ids") or ()),
            payload=_dict(body.get("payload")),
            template_id=_optional_str(body.get("template_id")),
            tenant_id=tenant_id,
            actor_id=actor_id,
            reviewer_id=_optional_str(body.get("reviewer_id")),
            reviewer_group=_optional_str(body.get("reviewer_group")),
        )
        return {
            "draft": _draft_json(artifact),
            "audit_events": [
                _audit_event_json(event) for event in self.draft_service.audit_events()
            ],
        }

    def get_draft(self, industry_id: str, artifact_id: str) -> dict | None:
        artifact = self.draft_service.get(artifact_id)
        if artifact is None or artifact.industry_id != industry_id:
            return None
        return _draft_json(artifact)

    def review_draft(
        self, tenant_id: str, actor_id: str, industry_id: str, artifact_id: str, body: dict
    ) -> dict | None:
        profile = self.profile_service.get(industry_id)
        if self.draft_service.get(artifact_id) is None:
            return None
        artifact = self.draft_service.transition(
            profile,
            artifact_id,
            to_status=str(body.get("to_status") or body.get("decision") or "in_review"),
            reviewer_id=_optional_str(body.get("reviewer_id")) or actor_id,
            reviewer_role=_optional_str(body.get("reviewer_role")) or "reviewer",
            tenant_id=tenant_id,
            actor_id=actor_id,
        )
        return {
            "draft": _draft_json(artifact),
            "audit_events": [
                _audit_event_json(event) for event in self.draft_service.audit_events()
            ],
        }

    def kpi(self, tenant_id: str, industry_id: str) -> dict:
        profile = self.profile_service.get(industry_id)
        values = self._kpi_values(profile, tenant_id)
        return {
            "tenant_id": tenant_id,
            "industry_id": industry_id,
            "kpis": [_kpi_value_json(value) for value in values],
        }

    def dashboard(self, tenant_id: str, industry_id: str, roles: tuple[str, ...]) -> dict:
        profile = self.profile_service.get(industry_id)
        result = self.dashboard_service.render(
            profile,
            tenant_id=tenant_id,
            roles=roles,
            kpi_values=self._kpi_values(profile, tenant_id),
        )
        return _dashboard_json(result)

    def governance_status(self, industry_id: str) -> dict:
        profile = self.profile_service.get(industry_id)
        return _governance_status_json(
            self.governance_service.status(
                profile,
                provider_facts={"no_train_required": True, "zero_retention_required": True},
                audit_facts={"audit_sink_ready": True},
                no_train_facts={"enforced": True},
                retention_facts={"retention_controls_ready": True},
            )
        )

    def profile_version_report(self) -> dict:
        profiles = self.profile_service.list_profiles()
        return {
            "stable": True,
            "profiles": [
                {
                    "industry_id": profile.industry_id,
                    "metadata_schema_version": profile.metadata_schema.version,
                    "workflow_count": len(profile.workflow_definitions),
                    "document_type_count": len(profile.document_types),
                }
                for profile in profiles
            ],
        }

    def _kpi_values(self, profile: IndustryProfile, tenant_id: str) -> tuple[KPIValue, ...]:
        return self.kpi_service.calculate(
            profile,
            tenant_id=tenant_id,
            audit_events=self.draft_service.audit_events(),
            draft_artifacts=self.draft_service.list_artifacts(profile),
        )


def _profile_json(profile: IndustryProfile) -> dict:
    return {
        "industry_id": profile.industry_id,
        "name": profile.name,
        "description": profile.description,
        "version": profile.metadata_schema.version,
        "document_types": [
            {
                "document_type": definition.document_type,
                "display_name": definition.display_name,
                "required_metadata_fields": list(definition.required_metadata_fields),
            }
            for definition in profile.document_types
        ],
        "metadata_schema": {
            "schema_id": profile.metadata_schema.schema_id,
            "version": profile.metadata_schema.version,
            "required_fields": list(profile.metadata_schema.required_fields),
            "indexed_fields": list(profile.metadata_schema.indexed_fields),
            "fields": [
                {
                    "field_name": field.field_name,
                    "field_type": field.field_type,
                    "required": field.required,
                    "searchable": field.searchable,
                    "filterable": field.filterable,
                }
                for field in profile.metadata_schema.fields
            ],
        },
        "workflows": [
            {
                "workflow_id": workflow.workflow_id,
                "name": workflow.name,
                "draft_artifact_type": workflow.draft_artifact_type,
                "review_required": workflow.review_required,
            }
            for workflow in profile.workflow_definitions
        ],
        "draft_artifact_types": [
            {
                "artifact_type": definition.artifact_type,
                "display_name": definition.display_name,
                "review_required": definition.review_required,
            }
            for definition in profile.draft_artifact_types
        ],
        "kpis": [
            {"kpi_id": definition.kpi_id, "name": definition.name, "formula": definition.formula}
            for definition in profile.kpi_definitions
        ],
        "dashboard_widgets": [
            {
                "widget_id": widget.widget_id,
                "name": widget.name,
                "kpi_ids": list(widget.kpi_ids),
                "required_role": widget.required_role,
            }
            for widget in profile.dashboard_widgets
        ],
        "governance_profile": {
            "governance_profile_id": profile.governance_profile.governance_profile_id,
            "no_train_policy_ref": profile.governance_profile.no_train_policy_ref,
            "retention_policy_refs": list(profile.governance_profile.retention_policy_refs),
            "provider_governance_requirements": list(
                profile.governance_profile.provider_governance_requirements
            ),
        },
    }


def _workflow_result_json(result: WorkflowResult) -> dict:
    return {
        "status": result.status,
        "text": result.text,
        "industry_id": result.profile.industry_id,
        "workflow_id": result.workflow.workflow_id,
        "review_required": result.review_required,
        "blocked": result.blocked,
        "risk_decision": {
            "risk_decision_id": result.risk_decision.risk_decision_id,
            "decision": result.risk_decision.decision,
            "risk_categories": list(result.risk_decision.risk_categories),
            "matched_rules": list(result.risk_decision.matched_rules),
        },
        "evidence_decision": _evidence_decision_json(result.evidence_decision),
        "citations": [_citation_json(citation) for citation in result.citations],
        "draft_artifact": _draft_json(result.draft_artifact) if result.draft_artifact else None,
        "audit_events": [_audit_event_json(event) for event in result.audit_events],
        "cost_events": [_cost_event_json(event) for event in result.cost_events],
    }


def _evidence_decision_json(decision: EvidenceDecision) -> dict:
    return {
        "passed": decision.passed,
        "status": decision.status,
        "reasons": list(decision.reasons),
        "valid_citation_count": len(decision.valid_citations),
        "invalid_citation_count": len(decision.invalid_citations),
    }


def _dashboard_json(result: DashboardResult) -> dict:
    return {
        "tenant_id": result.tenant_id,
        "industry_id": result.industry_id,
        "widgets": [_json_safe(widget) for widget in result.widgets],
        "kpis": [_kpi_value_json(value) for value in result.kpis],
        "denied_widget_ids": list(result.denied_widget_ids),
    }


def _governance_status_json(status: GovernanceStatus) -> dict:
    return {
        "industry_id": status.industry_id,
        "status": status.status,
        "no_train_enforced": status.no_train_enforced,
        "audit_ready": status.audit_ready,
        "provider_ready": status.provider_ready,
        "retention_ready": status.retention_ready,
        "facts": _json_safe(status.facts),
    }


def _draft_json(artifact: FrameworkDraftArtifact) -> dict:
    return {
        "artifact_id": artifact.artifact_id,
        "industry_id": artifact.industry_id,
        "artifact_type": artifact.artifact_type,
        "status": artifact.status,
        "created_by": artifact.created_by,
        "reviewer_id": artifact.reviewer_id,
        "reviewer_group": artifact.reviewer_group,
        "source_citations": [_citation_json(citation) for citation in artifact.source_citations],
        "source_document_ids": list(artifact.source_document_ids),
        "template_id": artifact.template_id,
        "audit_log_ref": artifact.audit_log_ref,
        "payload": _json_safe(artifact.payload),
    }


def _citation_json(citation: IndustryCitation) -> dict:
    return {
        "document_id": citation.document_id,
        "document_type": citation.document_type,
        "approval_status": citation.approval_status,
        "effective_date": citation.effective_date,
        "page": citation.page,
        "section": citation.section,
        "sheet_name": citation.sheet_name,
        "cell_range": citation.cell_range,
        "row_id": citation.row_id,
        "role": citation.role,
    }


def _audit_event_json(event: FrameworkAuditEvent) -> dict:
    return {
        "tenant_id": event.tenant_id,
        "industry_id": event.industry_id,
        "workflow_id": event.workflow_id,
        "action": event.action,
        "decision": event.decision,
        "actor_id": event.actor_id,
        "metadata": _json_safe(event.metadata),
    }


def _cost_event_json(event: FrameworkCostEvent) -> dict:
    return {
        "tenant_id": event.tenant_id,
        "industry_id": event.industry_id,
        "workflow_id": event.workflow_id,
        "kind": event.kind,
        "units": event.units,
        "metadata": _json_safe(event.metadata),
    }


def _kpi_value_json(value: KPIValue) -> dict:
    return {
        "kpi_id": value.kpi_id,
        "industry_id": value.industry_id,
        "tenant_id": value.tenant_id,
        "value": value.value,
        "source_event_count": value.source_event_count,
        "dimensions": _json_safe(value.dimensions),
    }


def _retention_decision_json(decision: RetentionDecision) -> dict:
    return {
        "document_id": decision.document_id,
        "industry_id": decision.industry_id,
        "retention_policy_ref": decision.retention_policy_ref,
        "retain_until": decision.retain_until,
        "export_allowed": decision.export_allowed,
        "delete_allowed": decision.delete_allowed,
        "audit_required": decision.audit_required,
    }


def _citations(body: dict) -> tuple[IndustryCitation, ...]:
    raw = body.get("citations") or ()
    return tuple(_citation(item) for item in raw if isinstance(item, dict))


def _citation(item: dict) -> IndustryCitation:
    return IndustryCitation(
        document_id=str(item.get("document_id") or ""),
        document_type=str(item.get("document_type") or "document"),
        approval_status=str(item.get("approval_status") or "approved"),
        effective_date=_optional_str(item.get("effective_date")) or "2026-01-10",
        page=_optional_int(item.get("page")),
        section=_optional_str(item.get("section")),
        sheet_name=_optional_str(item.get("sheet_name")),
        cell_range=_optional_str(item.get("cell_range")),
        row_id=_optional_str(item.get("row_id")),
        role=str(item.get("role") or "formal"),
    )


def _dict(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _optional_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(child) for key, child in value.items()}
    return value
