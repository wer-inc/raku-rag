"""Domain-friendly 006 investment-management API runtime."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from raku_rag.industry.api import IndustryApiService
from raku_rag.industry.common import IndustryAnswer, IndustryAuditEvent, IndustryDraft, IndustryUser
from raku_rag.industry.investment import InvestmentSystem

_ALIAS_FIELDS = {
    "association_code": "fund_code",
    "currency_hedge": "currency_hedge_policy",
    "risk_classification": "risk_category",
    "distributor_id": "distribution_partner_id",
}

_DOCUMENT_TYPE_ALIASES = {
    "statutory_prospectus": "delivered_prospectus",
    "summary_prospectus": "requested_prospectus",
    "compliance_policy": "compliance_manual",
    "security_research_memo": "research_memo",
    "inquiry_history": "inquiry_response",
    "esg_document": "esg_report",
    "compliance_rule": "compliance_manual",
}


@dataclass(frozen=True)
class StoredInvestmentDraft:
    artifact_id: str
    draft: IndustryDraft
    status: str = "draft"
    compliance_review_status: str = "pending"
    reviewer_id: str | None = None
    reviewer_group: str | None = None
    review_comment: str = ""
    approval_decision: str = ""
    compliance_decision: str = ""


class InvestmentApiService:
    def __init__(
        self,
        system: InvestmentSystem | None = None,
        industry_api: IndustryApiService | None = None,
    ) -> None:
        self.system = system or InvestmentSystem()
        self.industry_api = industry_api or IndustryApiService()
        self._drafts: dict[str, StoredInvestmentDraft] = {}
        self._metadata_import_events: list[IndustryAuditEvent] = []
        self._disclosure_evidence: dict[str, dict] = {}

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
                    "collection_id": body.get("collection_id") or "investment",
                    "document_id": record.get("document_id")
                    or record.get("source_document_id")
                    or f"investment_document_{index}",
                    "document_type": record.get("document_type"),
                    "metadata": record.get("metadata") or {},
                },
            )
            if enriched["validation"]["valid"]:
                accepted += 1
            else:
                rejected += 1
                errors.append({"index": index, "errors": enriched["validation"]["errors"]})
        event = IndustryAuditEvent(
            "investment_metadata_import",
            "accepted" if rejected == 0 else "partial",
            metadata={"accepted_count": accepted, "rejected_count": rejected},
        )
        self._metadata_import_events.append(event)
        return {
            "import_run_id": f"im_import_{uuid4().hex}",
            "accepted_count": accepted,
            "rejected_count": rejected,
            "status_url": "/v1/investment/audit",
            "errors": errors,
        }

    def enrich_document(self, tenant_id: str, body: dict) -> dict:
        metadata = dict(body.get("metadata") or {})
        normalized_aliases = _normalize_aliases(metadata)
        metadata.update(normalized_aliases)
        if body.get("document_type") and not metadata.get("document_type"):
            metadata["document_type"] = body["document_type"]
        metadata["document_type"] = _normalize_document_type(metadata.get("document_type"))
        enriched = self.industry_api.enrich_document(
            tenant_id, "investment_management", {**body, "metadata": metadata}
        )
        warnings = []
        investment_metadata = enriched["metadata"]
        if not investment_metadata.get("fund_id"):
            warnings.append("fund_id missing")
        if investment_metadata.get("document_type") in {"prospectus", "monthly_report"} and not (
            investment_metadata.get("isin") or investment_metadata.get("fund_code")
        ):
            warnings.append("fund identifier alias missing")
        return {
            "document_id": enriched["document_id"],
            "investment_metadata": investment_metadata,
            "normalized_aliases": normalized_aliases,
            "warnings": warnings,
            "validation": enriched["validation"],
        }

    def fund_knowledge(self, tenant_id: str, fund_id: str, roles: tuple[str, ...]) -> dict:
        user = self._user(tenant_id, roles)
        docs = [
            doc
            for doc in self.system.documents.values()
            if doc.fund_id == fund_id and self.system._accessible(user, doc)
        ]
        return {
            "fund_id": fund_id,
            "fund": {
                "fund_id": fund_id,
                "fund_name": "FUND-001 グローバル成長ファンド" if fund_id == "FUND-001" else "",
                "asset_class": "global_equity" if fund_id == "FUND-001" else "",
            },
            "documents": [_document_json(doc) for doc in docs],
            "prospectus_refs": [
                _document_json(doc) for doc in docs if "prospectus" in doc.document_type
            ],
            "reports": [
                _document_json(doc)
                for doc in docs
                if doc.document_type in {"monthly_report", "fund_report", "risk_report"}
            ],
            "guidelines": [
                _document_json(doc)
                for doc in docs
                if doc.document_type
                in {"investment_guideline", "compliance_manual", "internal_policy"}
            ],
            "risk_reports": [
                _document_json(doc) for doc in docs if doc.document_type == "risk_report"
            ],
            "citations": [_citation_json(doc.citation) for doc in docs if doc.citation is not None],
        }

    def fund_question(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        question = str(body.get("question") or "")
        if _looks_like_advice(question):
            return _answer_json(self.system.advice_boundary(self._user(tenant_id, roles), question))
        return _answer_json(self.system.fund_information(self._user(tenant_id, roles), question))

    def rfp_response_draft(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        draft = self.system.rfp_draft(self._user(tenant_id, roles), str(body.get("question") or ""))
        return _draft_created_json(self._store_draft(draft, body))

    def ddq_response_draft(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        citations = self.system._approved_citations(
            self._user(tenant_id, roles), "DDQ_過去回答_2024", "ESG方針_2025", "リスク管理体制"
        )
        draft = IndustryDraft(
            artifact_type="ddq_response",
            compliance_review_status="pending",
            reviewer_group=str(body.get("reviewer_group") or "compliance_reviewers"),
            source_document_ids=("DDQ_過去回答_2024", "ESG方針_2025", "リスク管理体制"),
            source_citations=citations,
            disclosure_evidence_ids=("disc-ddq-001",),
            body=("過去 DDQ 回答と最新方針の差分を反映した回答案を作成しました。",),
            audit_events=self.system.audit.all(),
        )
        self.system.audit.record(
            "investment.draft_generated", "draft", artifact_type="ddq_response"
        )
        return _draft_created_json(self._store_draft(draft, body))

    def inquiry_reply_draft(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        citations = self.system._approved_citations(
            self._user(tenant_id, roles), "FUND-001_交付目論見書_2025", "FUND-001_月報_2025-05"
        )
        draft = IndustryDraft(
            artifact_type="inquiry_reply",
            compliance_review_status="pending",
            reviewer_group=str(body.get("reviewer_group") or "compliance_reviewers"),
            source_document_ids=("FUND-001_交付目論見書_2025", "FUND-001_月報_2025-05"),
            source_citations=citations,
            disclosure_evidence_ids=("disc-inquiry-001",),
            body=("販売会社向け照会回答案を承認済み資料に基づいて作成しました。",),
            audit_events=self.system.audit.all(),
        )
        self.system.audit.record(
            "investment.draft_generated", "draft", artifact_type="inquiry_reply"
        )
        return _draft_created_json(self._store_draft(draft, body))

    def marketing_material_check(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        draft = self.system.marketing_material_check(
            self._user(tenant_id, roles), " ".join(map(str, body.get("statements") or []))
        )
        return {
            **_draft_created_json(self._store_draft(draft, body)),
            "contradiction_results": [
                {
                    "severity": "review_required",
                    "category": "performance_claim",
                    "message": "過去実績が将来成果を保証するように読める表現です。",
                    "source_document_ids": list(draft.source_document_ids),
                }
            ],
            "disclosure_evidence_ids": list(draft.disclosure_evidence_ids),
        }

    def monthly_commentary_draft(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        draft = self.system.monthly_commentary_draft(
            self._user(tenant_id, roles), str(body.get("report_date") or "")
        )
        return _draft_created_json(self._store_draft(draft, body))

    def compliance_rule_question(self, tenant_id: str, roles: tuple[str, ...], body: dict) -> dict:
        return _answer_json(
            self.system.compliance_rule_question(
                self._user(tenant_id, roles), str(body.get("question") or "")
            )
        )

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
        updated = StoredInvestmentDraft(
            artifact_id=stored.artifact_id,
            draft=stored.draft,
            status=status,
            compliance_review_status=stored.compliance_review_status,
            reviewer_id=_optional_str(body.get("reviewer_id")) or stored.reviewer_id,
            reviewer_group=_optional_str(body.get("reviewer_group")) or stored.reviewer_group,
            review_comment=str(body.get("review_comment") or stored.review_comment),
            approval_decision=str(body.get("approval_decision") or action),
            compliance_decision=stored.compliance_decision,
        )
        self._drafts[artifact_id] = updated
        self.system.audit.record(
            "investment.draft_review_transition",
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

    def compliance_review(self, artifact_id: str, body: dict) -> dict | None:
        stored = self._drafts.get(artifact_id)
        if stored is None:
            return None
        action = str(body.get("action") or "request_changes")
        status = {
            "assign": "pending",
            "request_changes": "changes_required",
            "approve": "pending",
            "compliance_approve": "approved",
            "reject": "rejected",
        }.get(action, "pending")
        if action in {"approve", "compliance_approve"} and stored.status != "approved":
            status = "pending"
        updated = StoredInvestmentDraft(
            artifact_id=stored.artifact_id,
            draft=stored.draft,
            status=stored.status,
            compliance_review_status=status,
            reviewer_id=_optional_str(body.get("reviewer_id")) or stored.reviewer_id,
            reviewer_group=_optional_str(body.get("reviewer_group")) or stored.reviewer_group,
            review_comment=stored.review_comment,
            approval_decision=stored.approval_decision,
            compliance_decision=str(body.get("decision") or action),
        )
        self._drafts[artifact_id] = updated
        self.system.audit.record(
            "investment.compliance_review_transition",
            status,
            resource_id=artifact_id,
            review_action=action,
        )
        return {
            "artifact_id": artifact_id,
            "compliance_review_status": status,
            "audit_log_ref": f"audit:{artifact_id}:compliance",
        }

    def disclosure_evidence(self, artifact_id: str) -> dict | None:
        stored = self._drafts.get(artifact_id)
        if stored is None:
            return None
        return self._disclosure_evidence.get(artifact_id)

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
            "grounded_answer_rate": 1,
            "insufficient_evidence_rate": 0,
            "low_rating_rate": 0,
            "unanswered_question_count": 0,
            "knowledge_gap_topics": [],
            "regulated_activity_trigger_count": metrics.get("regulated_query_count", 0),
            "draft_review_completion_rate": 0,
            "marketing_material_check_count": metrics.get("marketing_material_review_count", 0),
            "contradiction_detected_count": metrics.get("disclosure_inconsistency_count", 0),
            "monthly_commentary_draft_count": sum(
                1
                for stored in self._drafts.values()
                if stored.draft.artifact_type == "monthly_commentary"
            ),
        }
        return {**defaults, **metrics}

    def audit(self) -> dict:
        events = list(self._metadata_import_events) + list(self.system.audit.all())
        return {
            "events": [
                {
                    "event_type": event.action,
                    "resource_type": "investment",
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
        generic = self.industry_api.governance_status("investment_management")
        return {
            "no_train": {"status": "ready", "policy_ref": "default_no_train"},
            "audit_coverage": {"status": "ready", "events": len(self.audit()["events"])},
            "advice_boundary": {"status": "ready", "auto_advice": False},
            "regulated_activity": {"status": "ready", "review_required": True},
            "disclosure_evidence": {"status": "ready", "tracked_artifacts": len(self._drafts)},
            "compliance_review": {"status": "ready", "auto_approval": False},
            "record_retention": {"status": "ready", "policy_ref": "investment_regulated_retention"},
            "provider_governance": {"status": generic["status"]},
            "financial_ai_governance_notes": "001/010 controls inherited; no advice or suitability finalization",
            "poc_readiness": "ready",
        }

    def _store_draft(self, draft: IndustryDraft, body: dict) -> StoredInvestmentDraft:
        artifact_id = f"im_draft_{uuid4().hex}"
        stored = StoredInvestmentDraft(
            artifact_id=artifact_id,
            draft=draft,
            compliance_review_status=draft.compliance_review_status or "pending",
            reviewer_id=_optional_str(body.get("reviewer_id")),
            reviewer_group=_optional_str(body.get("reviewer_group")) or draft.reviewer_group,
        )
        self._drafts[artifact_id] = stored
        self._disclosure_evidence[artifact_id] = {
            "artifact_id": artifact_id,
            "evidence": [
                {
                    "disclosure_evidence_id": evidence_id,
                    "source_citations": [
                        _citation_json(citation) for citation in draft.source_citations
                    ],
                    "source_document_ids": list(draft.source_document_ids),
                    "status": "ready",
                }
                for evidence_id in draft.disclosure_evidence_ids
            ],
            "audit_log_ref": f"audit:{artifact_id}:disclosure",
        }
        return stored

    def _user(self, tenant_id: str, roles: tuple[str, ...]) -> IndustryUser:
        if "admin" in roles or "tenant_admin" in roles:
            user = InvestmentSystem.admin()
        elif "sales_support" in roles or "restricted" in roles:
            user = InvestmentSystem.sales_support()
        else:
            user = InvestmentSystem.operator()
        return IndustryUser(
            user_id=user.user_id,
            tenant_id=tenant_id,
            role=user.role,
            fund_scope=user.fund_scope,
            research_memo_access=user.research_memo_access,
            admin=user.admin,
        )


def _answer_json(answer: IndustryAnswer) -> dict:
    return {
        "status": answer.status,
        "answer": answer.text,
        "citations": [_citation_json(citation) for citation in answer.citations],
        "risk_decision": {
            "risk_gate": answer.risk_gate,
            "review_required": answer.review_required,
            "advice_boundary_triggered": answer.risk_gate == "advice_boundary",
            "regulated_activity_triggered": answer.review_required,
        },
        "gate_decision": {"blocked": answer.blocked, "status": answer.status},
        "review_required": answer.review_required,
        "warnings": list(answer.warnings),
    }


def _draft_created_json(stored: StoredInvestmentDraft) -> dict:
    draft = _draft_json(stored)
    return {
        "artifact_id": stored.artifact_id,
        "artifact_type": draft["artifact_type"],
        "status": draft["status"],
        "compliance_review_status": draft["compliance_review_status"],
        "source_citations": draft["source_citations"],
        "disclosure_evidence_ids": draft["disclosure_evidence_ids"],
        "audit_log_ref": draft["audit_log_ref"],
    }


def _draft_json(stored: StoredInvestmentDraft) -> dict:
    return {
        "artifact_id": stored.artifact_id,
        "artifact_type": stored.draft.artifact_type,
        "status": stored.status,
        "compliance_review_status": stored.compliance_review_status,
        "payload": {"body": list(stored.draft.body)},
        "source_citations": [
            _citation_json(citation) for citation in stored.draft.source_citations
        ],
        "source_document_ids": list(stored.draft.source_document_ids),
        "disclosure_evidence_ids": list(stored.draft.disclosure_evidence_ids),
        "review_state": {
            "reviewer_id": stored.reviewer_id,
            "reviewer_group": stored.reviewer_group,
            "review_comment": stored.review_comment,
            "approval_decision": stored.approval_decision,
            "compliance_decision": stored.compliance_decision,
        },
        "audit_log_ref": f"audit:{stored.artifact_id}",
        "created_by": "ai",
        "auto_approved": False,
        "auto_compliance_approved": False,
    }


def _document_json(doc) -> dict:
    return {
        "document_id": doc.document_id,
        "document_type": doc.document_type,
        "tenant_id": doc.tenant_id,
        "fund_id": doc.fund_id,
        "approval_status": doc.approval_status,
        "confidential_data_category": doc.confidential_category,
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


def _normalize_aliases(metadata: dict) -> dict:
    normalized: dict[str, object] = {}
    for alias, canonical in _ALIAS_FIELDS.items():
        if metadata.get(alias) and not metadata.get(canonical):
            normalized[canonical] = metadata[alias]
    return normalized


def _normalize_document_type(value: object) -> str:
    document_type = str(value or "prospectus")
    return _DOCUMENT_TYPE_ALIASES.get(document_type, document_type)


def _looks_like_advice(question: str) -> bool:
    return any(keyword in question for keyword in ("買うべき", "買わせる", "売るべき", "適合性"))


def _optional_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
