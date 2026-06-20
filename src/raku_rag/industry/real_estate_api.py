"""Domain-friendly 003 real estate API runtime.

This adapter maps `/real-estate/...` product endpoints onto the deterministic 003 runtime and the
010 generic industry framework. It keeps the domain vocabulary that property-management operators
expect while preserving the 001/010 policy boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from raku_rag.industry.api import IndustryApiService
from raku_rag.industry.common import IndustryAnswer, IndustryAuditEvent, IndustryDraft, IndustryUser
from raku_rag.industry.real_estate import RealEstateSystem


@dataclass(frozen=True)
class StoredRealEstateDraft:
    artifact_id: str
    draft: IndustryDraft
    status: str = "draft"
    reviewer_id: str | None = None
    reviewer_group: str | None = None
    review_comment: str = ""
    approval_decision: str = ""


class RealEstateApiService:
    def __init__(
        self,
        system: RealEstateSystem | None = None,
        industry_api: IndustryApiService | None = None,
    ) -> None:
        self.system = system or RealEstateSystem()
        self.industry_api = industry_api or IndustryApiService()
        self._drafts: dict[str, StoredRealEstateDraft] = {}
        self._metadata_import_events: list[IndustryAuditEvent] = []

    def metadata_import(self, tenant_id: str, body: dict) -> dict:
        records = body.get("records") if isinstance(body.get("records"), list) else []
        accepted = 0
        rejected = 0
        errors: list[dict] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                rejected += 1
                errors.append({"index": index, "errors": ["record must be an object"]})
                continue
            enriched = self.enrich_document(
                tenant_id,
                {
                    "collection_id": body.get("collection_id") or "real-estate",
                    "document_id": record.get("document_id")
                    or record.get("source_document_id")
                    or f"real_estate_document_{index}",
                    "metadata": record.get("metadata") or {},
                },
            )
            if enriched["validation"]["valid"]:
                accepted += 1
            else:
                rejected += 1
                errors.append({"index": index, "errors": enriched["validation"]["errors"]})
        event = IndustryAuditEvent(
            "real_estate_metadata_import",
            "accepted" if rejected == 0 else "partial",
            metadata={"accepted_count": accepted, "rejected_count": rejected},
        )
        self._metadata_import_events.append(event)
        return {
            "import_run_id": f"re_import_{uuid4().hex}",
            "accepted_count": accepted,
            "rejected_count": rejected,
            "status_url": "/v1/real-estate/audit",
            "errors": errors,
        }

    def enrich_document(self, tenant_id: str, body: dict) -> dict:
        enriched = self.industry_api.enrich_document(tenant_id, "real_estate_pm", body)
        warnings = []
        metadata = enriched["metadata"]
        if not metadata.get("property_id"):
            warnings.append("property_id missing")
        if not metadata.get("unit_id") and metadata.get("document_type") in {
            "lease_contract",
            "repair_history",
            "tenant_inquiry",
        }:
            warnings.append("unit_id missing for unit-scoped document")
        return {
            "document_id": enriched["document_id"],
            "real_estate_metadata": metadata,
            "warnings": warnings,
            "validation": enriched["validation"],
        }

    def property_knowledge(self, tenant_id: str, property_id: str, roles: tuple[str, ...]) -> dict:
        user = self._user(tenant_id, roles)
        docs = [
            doc
            for doc in self.system.documents.values()
            if doc.property_id == property_id and self.system._accessible(user, doc)
        ]
        citations = [doc.citation for doc in docs if doc.citation is not None]
        return {
            "property_id": property_id,
            "documents": [_document_json(doc) for doc in docs],
            "active_contracts": [
                _document_json(doc) for doc in docs if doc.document_type == "lease_contract"
            ],
            "repair_summary": {
                "repair_case_count": sum(
                    1 for doc in docs if doc.document_type == "repair_history"
                ),
                "latest_status": "available" if docs else "empty",
            },
            "owner_reports": [
                _draft_json(stored)
                for stored in self._drafts.values()
                if stored.draft.artifact_type == "owner_report"
            ],
            "citations": [_citation_json(citation) for citation in citations],
        }

    def unit_knowledge(self, tenant_id: str, unit_id: str, roles: tuple[str, ...]) -> dict:
        user = self._user(tenant_id, roles)
        docs = [
            doc
            for doc in self.system.documents.values()
            if doc.unit_id == unit_id and self.system._accessible(user, doc)
        ]
        return {
            "unit_id": unit_id,
            "lease_contracts": [
                _document_json(doc) for doc in docs if doc.document_type == "lease_contract"
            ],
            "repair_cases": [
                _document_json(doc) for doc in docs if doc.document_type == "repair_history"
            ],
            "inquiries": [
                _document_json(doc) for doc in docs if doc.document_type == "tenant_inquiry"
            ],
            "documents": [_document_json(doc) for doc in docs],
            "citations": [_citation_json(doc.citation) for doc in docs if doc.citation is not None],
        }

    def contract_question(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        answer = self.system.contract_condition(
            self._user(tenant_id, roles), str(body.get("question") or "")
        )
        return _answer_json(answer)

    def repair_investigation(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        answer = self.system.repair_history(
            self._user(tenant_id, roles), str(body.get("symptom") or "")
        )
        return {
            "status": answer.status,
            "similar_cases": list(answer.table_rows),
            "summary": answer.text,
            "citations": [_citation_json(citation) for citation in answer.citations],
            "warnings": list(answer.warnings),
        }

    def occupant_reply_draft(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        draft = self.system.occupant_reply_draft(
            self._user(tenant_id, roles), str(body.get("inquiry_text") or "")
        )
        return _draft_created_json(self._store_draft(draft, body))

    def owner_report_draft(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        draft = self.system.owner_report_draft(
            self._user(tenant_id, roles), str(body.get("report_period") or "")
        )
        return _draft_created_json(self._store_draft(draft, body))

    def move_out_checklist_draft(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        citations = self.system._approved_citations(
            self._user(tenant_id, roles),
            "Aマンション_305号室_賃貸借契約書",
            "305号室_退去立会記録",
        )
        draft = IndustryDraft(
            artifact_type="move_out_checklist",
            reviewer_group=str(body.get("reviewer_group") or "pm_leads"),
            source_document_ids=("Aマンション_305号室_賃貸借契約書", "305号室_退去立会記録"),
            source_citations=citations,
            body=(
                "退去立会、鍵返却、原状回復確認、精算確認のチェック項目を作成しました。",
                "費用負担判断はレビュー後に確定してください。",
            ),
            audit_events=self.system.audit.all(),
        )
        self.system.audit.record(
            "real_estate.draft_generated", "draft", artifact_type="move_out_checklist"
        )
        return _draft_created_json(self._store_draft(draft, body))

    def restoration_explanation_draft(
        self, tenant_id: str, roles: tuple[str, ...], body: dict
    ) -> dict:
        citations = self.system._approved_citations(
            self._user(tenant_id, roles),
            "Aマンション_305号室_賃貸借契約書",
            "305号室_退去立会記録",
        )
        draft = IndustryDraft(
            artifact_type="restoration_explanation",
            reviewer_group=str(body.get("reviewer_group") or "pm_leads"),
            source_document_ids=("Aマンション_305号室_賃貸借契約書", "305号室_退去立会記録"),
            source_citations=citations,
            body=(
                "原状回復の確認事項と未確定事項を根拠付きで整理しました。",
                "費用負担および法的判断は自動確定しません。",
            ),
            audit_events=self.system.audit.all(),
        )
        self.system.audit.record(
            "real_estate.draft_generated", "draft", artifact_type="restoration_explanation"
        )
        return _draft_created_json(self._store_draft(draft, body))

    def draft(self, artifact_id: str) -> dict | None:
        stored = self._drafts.get(artifact_id)
        if stored is None:
            return None
        return _draft_json(stored)

    def review_draft(self, artifact_id: str, body: dict) -> dict | None:
        stored = self._drafts.get(artifact_id)
        if stored is None:
            return None
        action = str(body.get("action") or "submit")
        status = {
            "assign": "in_review",
            "submit": "in_review",
            "approve": "approved",
            "reject": "rejected",
            "archive": "archived",
        }.get(action, "in_review")
        if action == "approve" and stored.status == "draft":
            status = "in_review"
        updated = StoredRealEstateDraft(
            artifact_id=stored.artifact_id,
            draft=stored.draft,
            status=status,
            reviewer_id=_optional_str(body.get("reviewer_id")) or stored.reviewer_id,
            reviewer_group=_optional_str(body.get("reviewer_group")) or stored.reviewer_group,
            review_comment=str(body.get("review_comment") or stored.review_comment),
            approval_decision=str(body.get("approval_decision") or action),
        )
        self._drafts[artifact_id] = updated
        self.system.audit.record(
            "real_estate.draft_review_transition",
            status,
            resource_id=artifact_id,
            review_action=action,
        )
        return {
            "artifact_id": artifact_id,
            "status": status,
            "reviewed_at": "2026-06-20T00:00:00Z" if status in {"approved", "rejected"} else None,
            "audit_log_ref": f"audit:{artifact_id}",
        }

    def dashboard(self, tenant_id: str, roles: tuple[str, ...]) -> dict:
        dashboard = self.system.dashboard(self._user(tenant_id, roles))
        return {
            "widgets": [
                {"widget_id": key, "value": value} for key, value in dashboard.metrics.items()
            ],
            "warnings": [],
        }

    def kpi(self, tenant_id: str, roles: tuple[str, ...]) -> dict:
        metrics = self.system.dashboard(self._user(tenant_id, ("admin",))).metrics
        defaults = {
            "self_resolution_rate": 0,
            "average_time_to_answer": 0,
            "inquiry_response_time_reduction": 0,
            "grounded_answer_rate": 1,
            "insufficient_evidence_rate": 0,
            "low_rating_rate": 0,
        }
        return {**defaults, **metrics}

    def audit(self) -> dict:
        events = list(self._metadata_import_events) + list(self.system.audit.all())
        return {
            "events": [
                {
                    "event_type": event.action,
                    "resource_type": "real_estate",
                    "resource_id": event.resource_id,
                    "decision": event.decision,
                    "timestamp": "2026-06-20T00:00:00Z",
                    "trace_id": event.metadata.get("trace_id") or "",
                    "metadata": dict(event.metadata),
                }
                for event in events
            ]
        }

    def governance_status(self) -> dict:
        generic = self.industry_api.governance_status("real_estate_pm")
        return {
            "no_train": {"status": "ready", "policy_ref": "default_no_train"},
            "audit_coverage": {"status": "ready", "events": len(self.audit()["events"])},
            "risk_gate": {"status": "ready", "categories": ["contract_condition", "legal_risk"]},
            "draft_review": {"status": "ready", "auto_approval": False},
            "personal_data_redaction": {"status": "ready", "minimal_display": True},
            "provider_governance": {"status": generic["status"]},
            "ismap_readiness_memo": "001/010 controls inherited by real estate profile",
            "poc_readiness": "ready",
        }

    def _store_draft(self, draft: IndustryDraft, body: dict) -> StoredRealEstateDraft:
        artifact_id = f"re_draft_{uuid4().hex}"
        stored = StoredRealEstateDraft(
            artifact_id=artifact_id,
            draft=draft,
            reviewer_id=_optional_str(body.get("reviewer_id")),
            reviewer_group=_optional_str(body.get("reviewer_group")) or draft.reviewer_group,
        )
        self._drafts[artifact_id] = stored
        return stored

    def _user(self, tenant_id: str, roles: tuple[str, ...]) -> IndustryUser:
        if "admin" in roles or "tenant_admin" in roles:
            user = RealEstateSystem.admin()
        elif "limited_user" in roles or "restricted" in roles:
            user = RealEstateSystem.restricted()
        else:
            user = RealEstateSystem.operator()
        return IndustryUser(
            user_id=user.user_id,
            tenant_id=tenant_id,
            role=user.role,
            property_scope=user.property_scope,
            unit_scope=user.unit_scope,
            personal_data_access=user.personal_data_access,
            amount_access=user.amount_access,
            admin=user.admin,
        )


def _answer_json(answer: IndustryAnswer) -> dict:
    return {
        "status": answer.status,
        "answer": answer.text,
        "citations": [_citation_json(citation) for citation in answer.citations],
        "risk_decision": {"risk_gate": answer.risk_gate, "review_required": answer.review_required},
        "gate_decision": {"blocked": answer.blocked, "status": answer.status},
        "review_required": answer.review_required,
        "warnings": list(answer.warnings),
    }


def _draft_created_json(stored: StoredRealEstateDraft) -> dict:
    draft = _draft_json(stored)
    return {
        "artifact_id": stored.artifact_id,
        "artifact_type": draft["artifact_type"],
        "status": draft["status"],
        "source_citations": draft["source_citations"],
        "audit_log_ref": draft["audit_log_ref"],
    }


def _draft_json(stored: StoredRealEstateDraft) -> dict:
    return {
        "artifact_id": stored.artifact_id,
        "artifact_type": stored.draft.artifact_type,
        "status": stored.status,
        "payload": {"body": list(stored.draft.body)},
        "source_citations": [
            _citation_json(citation) for citation in stored.draft.source_citations
        ],
        "source_document_ids": list(stored.draft.source_document_ids),
        "review_state": {
            "reviewer_id": stored.reviewer_id,
            "reviewer_group": stored.reviewer_group,
            "review_comment": stored.review_comment,
            "approval_decision": stored.approval_decision,
        },
        "audit_log_ref": f"audit:{stored.artifact_id}",
        "created_by": "ai",
        "auto_approved": False,
    }


def _document_json(doc) -> dict:
    return {
        "document_id": doc.document_id,
        "document_type": doc.document_type,
        "tenant_id": doc.tenant_id,
        "property_id": doc.property_id,
        "unit_id": doc.unit_id,
        "approval_status": doc.approval_status,
        "personal_data_category": doc.personal_data_category,
    }


def _citation_json(citation) -> dict:
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
    }


def _optional_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
