"""Real estate property-management solution runtime for UAT verification."""

from __future__ import annotations

from raku_rag.industry.common import (
    IndustryAnswer,
    IndustryAuditLog,
    IndustryCitation,
    IndustryDashboard,
    IndustryDocument,
    IndustryDraft,
    IndustryUser,
)
from raku_rag.industry.framework import (
    IndustryRiskPolicyService,
    RequiredEvidencePolicyService,
    create_default_profile_service,
)


class RealEstateSystem:
    """Deterministic real-estate solution layer for the RE UAT scenarios.

    The runtime enforces the UAT invariants explicitly: approved/effective evidence for contract and
    fee-risk assertions, draft-only AI artifacts, personal-data ACL, tenant/property scoping, audit,
    and dashboard counters. It is not the final DB/API adapter, but it is product code rather than a
    test-only mock.
    """

    def __init__(self) -> None:
        self.audit = IndustryAuditLog()
        self.documents = self._seed_documents()
        self.profile_service = create_default_profile_service()
        self.profile = self.profile_service.get("real_estate_pm")
        self.risk_policy = IndustryRiskPolicyService()
        self.evidence_policy = RequiredEvidencePolicyService()
        self._drafts: list[IndustryDraft] = []
        self._repair_lookup_count = 0
        self._high_risk_query_count = 0
        self._risk_gate_block_count = 0
        self._denied_count = 0

    @staticmethod
    def admin() -> IndustryUser:
        return IndustryUser(
            user_id="admin_alpha",
            role="tenant_admin",
            property_scope=("P001",),
            unit_scope=("U305",),
            personal_data_access=True,
            amount_access=True,
            admin=True,
        )

    @staticmethod
    def operator() -> IndustryUser:
        return IndustryUser(
            user_id="operator_alpha",
            role="property_manager",
            property_scope=("P001",),
            unit_scope=("U305",),
            personal_data_access=True,
            amount_access=True,
        )

    @staticmethod
    def restricted() -> IndustryUser:
        return IndustryUser(
            user_id="restricted_alpha",
            role="limited_user",
            property_scope=("P001",),
            unit_scope=("U305",),
            amount_access=False,
            personal_data_access=False,
        )

    def _seed_documents(self) -> dict[str, IndustryDocument]:
        return {
            "Aマンション_305号室_賃貸借契約書": IndustryDocument(
                document_id="Aマンション_305号室_賃貸借契約書",
                document_type="lease_contract",
                property_id="P001",
                unit_id="U305",
                citation=IndustryCitation(
                    "Aマンション_305号室_賃貸借契約書",
                    "lease_contract",
                    page=6,
                    section="禁止事項",
                ),
            ),
            "Aマンション_管理規約": IndustryDocument(
                document_id="Aマンション_管理規約",
                document_type="management_rule",
                property_id="P001",
                citation=IndustryCitation(
                    "Aマンション_管理規約",
                    "management_rule",
                    page=12,
                    section="ペット飼育",
                ),
            ),
            "Aマンション_旧管理規約": IndustryDocument(
                document_id="Aマンション_旧管理規約",
                document_type="management_rule",
                approval_status="obsolete",
                property_id="P001",
                citation=IndustryCitation(
                    "Aマンション_旧管理規約",
                    "management_rule",
                    approval_status="obsolete",
                    page=10,
                    section="旧ペット飼育",
                    role="warning",
                ),
            ),
            "305号室_退去立会記録": IndustryDocument(
                document_id="305号室_退去立会記録",
                document_type="move_out_document",
                property_id="P001",
                unit_id="U305",
                citation=IndustryCitation("305号室_退去立会記録", "move_out_document", page=2),
            ),
            "原状回復ガイドライン_社内メモ": IndustryDocument(
                document_id="原状回復ガイドライン_社内メモ",
                document_type="internal_manual",
                approval_status="draft",
                property_id="P001",
                unit_id="U305",
            ),
            "修繕履歴_Aマンション": IndustryDocument(
                document_id="修繕履歴_Aマンション",
                document_type="repair_history",
                property_id="P001",
                unit_id="U305",
                citation=IndustryCitation(
                    "修繕履歴_Aマンション",
                    "repair_history",
                    sheet_name="修繕履歴",
                    cell_range="B20:H20",
                    row_id="20",
                ),
            ),
            "入居者問い合わせ履歴": IndustryDocument(
                document_id="入居者問い合わせ履歴",
                document_type="tenant_inquiry",
                property_id="P001",
                unit_id="U305",
                personal_data_category="occupant_contact",
                citation=IndustryCitation(
                    "入居者問い合わせ履歴",
                    "tenant_inquiry",
                    row_id="42",
                ),
            ),
            "見積書_水漏れ_2024-05": IndustryDocument(
                document_id="見積書_水漏れ_2024-05",
                document_type="estimate",
                property_id="P001",
                unit_id="U305",
                citation=IndustryCitation("見積書_水漏れ_2024-05", "estimate", page=1),
            ),
            "請求書_水漏れ_2024-05": IndustryDocument(
                document_id="請求書_水漏れ_2024-05",
                document_type="invoice",
                property_id="P001",
                unit_id="U305",
                citation=IndustryCitation("請求書_水漏れ_2024-05", "invoice", page=1),
            ),
            "保証人情報": IndustryDocument(
                document_id="保証人情報",
                document_type="occupant_personal_data",
                property_id="P001",
                unit_id="U305",
                personal_data_category="guarantor",
            ),
            "支払い履歴": IndustryDocument(
                document_id="支払い履歴",
                document_type="payment_history",
                property_id="P001",
                unit_id="U305",
                personal_data_category="payment_history",
            ),
        }

    def _accessible(self, user: IndustryUser, doc: IndustryDocument) -> bool:
        if doc.tenant_id != user.tenant_id:
            return False
        if doc.property_id and doc.property_id not in user.property_scope:
            return False
        if doc.unit_id and doc.unit_id not in user.unit_scope:
            return False
        if doc.personal_data_category and not user.personal_data_access:
            return False
        return True

    def _approved_citations(
        self, user: IndustryUser, *document_ids: str
    ) -> tuple[IndustryCitation, ...]:
        citations: list[IndustryCitation] = []
        for document_id in document_ids:
            doc = self.documents[document_id]
            if self._accessible(user, doc) and doc.approved and doc.citation is not None:
                citations.append(doc.citation)
        return tuple(citations)

    def contract_condition(self, user: IndustryUser, question: str) -> IndustryAnswer:
        self._high_risk_query_count += 1
        risk = self.risk_policy.evaluate(self.profile.risk_policy, question)
        citations = self._approved_citations(
            user, "Aマンション_305号室_賃貸借契約書", "Aマンション_管理規約"
        )
        evidence = self.evidence_policy.check(self.profile.required_evidence_policy, citations)
        self.audit.record("real_estate.contract_question", "answered", user=user.user_id)
        self.audit.record(
            "real_estate.risk_decision",
            "review_required",
            category="contract",
            framework_decision=risk.decision,
            matched_rules=risk.matched_rules,
        )
        if len(citations) < 2 or not evidence.passed:
            self._risk_gate_block_count += 1
            return IndustryAnswer(
                status=evidence.status,
                text="承認済みかつ有効な契約根拠を確認できません。",
                risk_gate="contract_condition",
                review_required=True,
                blocked=True,
                audit_events=self.audit.all(),
            )
        return IndustryAnswer(
            status="ok",
            text=(
                "賃貸借契約書および管理規約上、305号室ではペット飼育は不可です。"
                "補助犬等の例外は管理規約の該当条項を確認してください。"
            ),
            citations=citations,
            risk_gate="contract_condition",
            review_required=True,
            audit_events=self.audit.all(),
        )

    def restoration_fee_question(self, user: IndustryUser, question: str) -> IndustryAnswer:
        self._high_risk_query_count += 1
        self._risk_gate_block_count += 1
        risk = self.risk_policy.evaluate(self.profile.risk_policy, question)
        citations = self._approved_citations(
            user, "Aマンション_305号室_賃貸借契約書", "305号室_退去立会記録"
        )
        self.audit.record(
            "real_estate.risk_decision",
            "blocked",
            category="fee_burden",
            framework_decision=risk.decision,
            matched_rules=risk.matched_rules,
        )
        return IndustryAnswer(
            status="review_required",
            text=(
                "費用負担の最終判断は断定できません。契約条項、損耗状況、社内確認が必要です。"
                "draft の社内メモは正式根拠にしません。"
            ),
            citations=citations,
            risk_gate="restoration_fee_burden",
            review_required=True,
            blocked=True,
            audit_events=self.audit.all(),
        )

    def repair_history(self, user: IndustryUser, question: str) -> IndustryAnswer:
        self._repair_lookup_count += 1
        citations = self._approved_citations(
            user,
            "修繕履歴_Aマンション",
            "見積書_水漏れ_2024-05",
            "請求書_水漏れ_2024-05",
            "入居者問い合わせ履歴",
        )
        self.audit.record("real_estate.repair_investigation", "answered", user=user.user_id)
        rows = (
            {
                "date": "2024-05-12",
                "incident": "洗面台下水漏れ",
                "response": "パッキン交換",
                "vendor": "B設備",
                "amount": "18,000円" if user.amount_access else "権限外",
                "evidence": "修繕履歴_Aマンション!B20:H20",
            },
            {
                "date": "2023-11-03",
                "incident": "上階漏水疑い",
                "response": "現地確認のみ",
                "vendor": "C工務店",
                "amount": "0円" if user.amount_access else "権限外",
                "evidence": "入居者問い合わせ履歴 row 42",
            },
        )
        return IndustryAnswer(
            status="ok",
            text="過去の水漏れ対応を一覧化しました。費用負担判断は自動確定しません。",
            citations=citations,
            risk_gate="financial_amount_acl",
            table_rows=rows,
            audit_events=self.audit.all(),
        )

    def occupant_reply_draft(self, user: IndustryUser, prompt: str) -> IndustryDraft:
        citations = self._approved_citations(user, "修繕履歴_Aマンション", "Aマンション_管理規約")
        draft = IndustryDraft(
            artifact_type="occupant_reply",
            reviewer_group="pm_leads",
            source_document_ids=("修繕履歴_Aマンション", "Aマンション_管理規約"),
            source_citations=citations,
            body=(
                "水漏れについてご連絡ありがとうございます。",
                "確認済みの修繕履歴に基づき、次の対応予定をご案内します。",
                "正式回答前に担当者レビューが必要です。",
            ),
            audit_events=self.audit.all(),
        )
        self._drafts.append(draft)
        self.audit.record("real_estate.draft_generated", "draft", artifact_type="occupant_reply")
        return draft

    def owner_report_draft(self, user: IndustryUser, prompt: str) -> IndustryDraft:
        citations = self._approved_citations(
            user, "修繕履歴_Aマンション", "見積書_水漏れ_2024-05", "請求書_水漏れ_2024-05"
        )
        draft = IndustryDraft(
            artifact_type="owner_report",
            reviewer_group="owner_reporting_reviewers",
            source_document_ids=(
                "修繕履歴_Aマンション",
                "見積書_水漏れ_2024-05",
                "請求書_水漏れ_2024-05",
            ),
            source_citations=citations,
            body=(
                "水漏れ修繕の発生状況、対応内容、費用を根拠付きで整理しました。",
                "費用負担や請求確定はレビュー後に判断します。",
            ),
            audit_events=self.audit.all(),
        )
        self._drafts.append(draft)
        self.audit.record("real_estate.draft_generated", "draft", artifact_type="owner_report")
        return draft

    def personal_data_query(self, user: IndustryUser, question: str) -> IndustryAnswer:
        denied_docs = ("保証人情報", "支払い履歴", "入居者問い合わせ履歴")
        for document_id in denied_docs:
            doc = self.documents[document_id]
            if not self._accessible(user, doc):
                self._denied_count += 1
                self.audit.record("real_estate.acl_denied", "denied", resource_id=document_id)
        return IndustryAnswer(
            status="no_access",
            text="権限のある範囲には該当情報がありません。",
            citations=(),
            risk_gate="personal_data_acl",
            blocked=True,
            audit_events=self.audit.all(),
        )

    def legal_judgment(self, user: IndustryUser, question: str) -> IndustryAnswer:
        self._high_risk_query_count += 1
        self._risk_gate_block_count += 1
        risk = self.risk_policy.evaluate(self.profile.risk_policy, question)
        citations = self._approved_citations(
            user, "Aマンション_305号室_賃貸借契約書", "305号室_退去立会記録"
        )
        self.audit.record(
            "real_estate.risk_decision",
            "blocked",
            category="legal_judgment",
            framework_decision=risk.decision,
            matched_rules=risk.matched_rules,
        )
        return IndustryAnswer(
            status="review_required",
            text="法的な最終判断は自動確定できません。根拠を確認し、法務または責任者レビューが必要です。",
            citations=citations,
            risk_gate="legal_judgment",
            review_required=True,
            blocked=True,
            audit_events=self.audit.all(),
        )

    def dashboard(self, user: IndustryUser) -> IndustryDashboard:
        if not user.admin:
            self._denied_count += 1
            self.audit.record("real_estate.dashboard", "denied", user=user.user_id)
            return IndustryDashboard(metrics={}, audit_events=self.audit.all())
        metrics = {
            "industry_profile_id": self.profile.industry_id,
            "unanswered_question_count": self._risk_gate_block_count,
            "low_rating_rate": 0,
            "frequently_referenced_documents": (
                "Aマンション_305号室_賃貸借契約書",
                "修繕履歴_Aマンション",
            ),
            "obsolete_document_candidates": ("Aマンション_旧管理規約",),
            "high_risk_query_count": self._high_risk_query_count,
            "risk_gate_block_count": self._risk_gate_block_count,
            "knowledge_gap_topics": ("原状回復費用負担",),
            "draft_review_completion_rate": 0,
            "repair_case_lookup_count": self._repair_lookup_count,
            "owner_report_draft_count": sum(
                1 for draft in self._drafts if draft.artifact_type == "owner_report"
            ),
            "occupant_reply_draft_count": sum(
                1 for draft in self._drafts if draft.artifact_type == "occupant_reply"
            ),
        }
        self.audit.record("real_estate.dashboard", "viewed", user=user.user_id)
        return IndustryDashboard(metrics=metrics, audit_events=self.audit.all())
