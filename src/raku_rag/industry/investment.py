"""Investment-management / mutual-fund solution runtime for UAT verification."""

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


class InvestmentSystem:
    """Deterministic investment solution layer for INV UAT scenarios."""

    def __init__(self) -> None:
        self.audit = IndustryAuditLog()
        self.documents = self._seed_documents()
        self.profile_service = create_default_profile_service()
        self.profile = self.profile_service.get("investment_management")
        self.risk_policy = IndustryRiskPolicyService()
        self.evidence_policy = RequiredEvidencePolicyService()
        self._drafts: list[IndustryDraft] = []
        self._regulated_query_count = 0
        self._advice_boundary_trigger_count = 0
        self._compliance_gate_block_count = 0
        self._disclosure_inconsistency_count = 0
        self._marketing_material_review_count = 0

    @staticmethod
    def admin() -> IndustryUser:
        return IndustryUser(
            user_id="admin_alpha",
            role="tenant_admin",
            fund_scope=("FUND-001",),
            research_memo_access=True,
            admin=True,
        )

    @staticmethod
    def operator() -> IndustryUser:
        return IndustryUser(
            user_id="operator_alpha",
            role="product_staff",
            fund_scope=("FUND-001",),
        )

    @staticmethod
    def sales_support() -> IndustryUser:
        return IndustryUser(
            user_id="sales_support_alpha",
            role="sales_support",
            fund_scope=("FUND-001",),
            research_memo_access=False,
        )

    def _seed_documents(self) -> dict[str, IndustryDocument]:
        return {
            "FUND-001_交付目論見書_2025": IndustryDocument(
                document_id="FUND-001_交付目論見書_2025",
                document_type="delivered_prospectus",
                fund_id="FUND-001",
                citation=IndustryCitation(
                    "FUND-001_交付目論見書_2025",
                    "delivered_prospectus",
                    page=8,
                    section="信託報酬・投資方針・為替ヘッジ",
                ),
            ),
            "FUND-001_請求目論見書_2025": IndustryDocument(
                document_id="FUND-001_請求目論見書_2025",
                document_type="requested_prospectus",
                fund_id="FUND-001",
                citation=IndustryCitation(
                    "FUND-001_請求目論見書_2025", "requested_prospectus", page=21
                ),
            ),
            "FUND-001_月報_2025-05": IndustryDocument(
                document_id="FUND-001_月報_2025-05",
                document_type="monthly_report",
                fund_id="FUND-001",
                citation=IndustryCitation("FUND-001_月報_2025-05", "monthly_report", page=2),
            ),
            "FUND-001_旧販売用資料": IndustryDocument(
                document_id="FUND-001_旧販売用資料",
                document_type="marketing_material",
                fund_id="FUND-001",
                approval_status="obsolete",
            ),
            "DDQ_過去回答_2024": IndustryDocument(
                document_id="DDQ_過去回答_2024",
                document_type="ddq",
                fund_id="FUND-001",
                citation=IndustryCitation("DDQ_過去回答_2024", "ddq", page=3),
            ),
            "運用体制資料_2025": IndustryDocument(
                document_id="運用体制資料_2025",
                document_type="product_summary",
                fund_id="FUND-001",
                citation=IndustryCitation("運用体制資料_2025", "product_summary", page=4),
            ),
            "ESG方針_2025": IndustryDocument(
                document_id="ESG方針_2025",
                document_type="esg_report",
                fund_id="FUND-001",
                citation=IndustryCitation("ESG方針_2025", "esg_report", page=2),
            ),
            "リスク管理体制": IndustryDocument(
                document_id="リスク管理体制",
                document_type="risk_report",
                fund_id="FUND-001",
                citation=IndustryCitation("リスク管理体制", "risk_report", page=5),
            ),
            "FUND-001_販売用資料_draft": IndustryDocument(
                document_id="FUND-001_販売用資料_draft",
                document_type="marketing_material",
                fund_id="FUND-001",
                approval_status="draft",
            ),
            "パフォーマンス要因分析_2025-05": IndustryDocument(
                document_id="パフォーマンス要因分析_2025-05",
                document_type="risk_report",
                fund_id="FUND-001",
                citation=IndustryCitation(
                    "パフォーマンス要因分析_2025-05",
                    "risk_report",
                    sheet_name="要因分析",
                    cell_range="B4:G20",
                ),
            ),
            "運用会議メモ_2025-05": IndustryDocument(
                document_id="運用会議メモ_2025-05",
                document_type="investment_committee_minutes",
                fund_id="FUND-001",
                confidential_category="internal_minutes",
                citation=IndustryCitation(
                    "運用会議メモ_2025-05", "investment_committee_minutes", page=1
                ),
            ),
            "コンプライアンス規程_販売資料": IndustryDocument(
                document_id="コンプライアンス規程_販売資料",
                document_type="compliance_manual",
                fund_id="FUND-001",
                citation=IndustryCitation(
                    "コンプライアンス規程_販売資料", "compliance_manual", page=7
                ),
            ),
            "社内規程_広告審査": IndustryDocument(
                document_id="社内規程_広告審査",
                document_type="internal_policy",
                fund_id="FUND-001",
                citation=IndustryCitation("社内規程_広告審査", "internal_policy", page=11),
            ),
            "FUND-002_運用会議メモ": IndustryDocument(
                document_id="FUND-002_運用会議メモ",
                document_type="investment_committee_minutes",
                fund_id="FUND-002",
                confidential_category="investment_team_only",
            ),
            "FUND-002_銘柄調査メモ": IndustryDocument(
                document_id="FUND-002_銘柄調査メモ",
                document_type="research_memo",
                fund_id="FUND-002",
                confidential_category="research_memo",
            ),
        }

    def _accessible(self, user: IndustryUser, doc: IndustryDocument) -> bool:
        if doc.tenant_id != user.tenant_id:
            return False
        if doc.fund_id and doc.fund_id not in user.fund_scope:
            return False
        if doc.document_type == "research_memo" and not user.research_memo_access:
            return False
        if doc.confidential_category == "investment_team_only" and user.role not in {
            "tenant_admin",
            "fund_manager",
            "analyst",
        }:
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

    def fund_information(self, user: IndustryUser, question: str) -> IndustryAnswer:
        self._regulated_query_count += 1
        risk = self.risk_policy.evaluate(self.profile.risk_policy, question)
        citations = self._approved_citations(
            user, "FUND-001_交付目論見書_2025", "FUND-001_請求目論見書_2025"
        )
        evidence = self.evidence_policy.check(self.profile.required_evidence_policy, citations)
        self.audit.record("investment.fund_question", "answered", user=user.user_id)
        self.audit.record(
            "investment.financial_risk_decision",
            "review_required",
            category="fund_fact",
            framework_decision=risk.decision,
            matched_rules=risk.matched_rules,
        )
        if not evidence.passed:
            return IndustryAnswer(
                status=evidence.status,
                text="承認済みかつ有効な投信根拠を確認できません。",
                citations=evidence.valid_citations,
                risk_gate="regulated_fund_fact",
                review_required=True,
                blocked=True,
                audit_events=self.audit.all(),
            )
        return IndustryAnswer(
            status="ok",
            text=(
                "FUND-001 の信託報酬は最新目論見書の記載を根拠に確認します。"
                "主要投資対象、為替ヘッジ方針、リスク分類は as-of/effective date 付きで示します。"
            ),
            citations=citations,
            risk_gate="regulated_fund_fact",
            review_required=True,
            audit_events=self.audit.all(),
        )

    def advice_boundary(self, user: IndustryUser, question: str) -> IndustryAnswer:
        self._regulated_query_count += 1
        self._advice_boundary_trigger_count += 1
        self._compliance_gate_block_count += 1
        risk = self.risk_policy.evaluate(self.profile.risk_policy, question)
        citations = self._approved_citations(
            user, "FUND-001_交付目論見書_2025", "FUND-001_月報_2025-05"
        )
        self.audit.record(
            "investment.advice_boundary",
            "blocked",
            user=user.user_id,
            framework_decision=risk.decision,
            matched_rules=risk.matched_rules,
        )
        return IndustryAnswer(
            status="blocked",
            text=(
                "投資助言、売買推奨、個別顧客への適合性判断は自動では行えません。"
                "承認済み資料に基づく商品事実の要約のみ可能で、コンプライアンスレビューが必要です。"
            ),
            citations=citations,
            risk_gate="advice_boundary",
            review_required=True,
            blocked=True,
            audit_events=self.audit.all(),
        )

    def rfp_draft(self, user: IndustryUser, prompt: str) -> IndustryDraft:
        citations = self._approved_citations(
            user, "DDQ_過去回答_2024", "運用体制資料_2025", "ESG方針_2025", "リスク管理体制"
        )
        draft = IndustryDraft(
            artifact_type="rfp_response",
            compliance_review_status="pending",
            reviewer_group="compliance_reviewers",
            source_document_ids=(
                "DDQ_過去回答_2024",
                "運用体制資料_2025",
                "ESG方針_2025",
                "リスク管理体制",
            ),
            source_citations=citations,
            disclosure_evidence_ids=("disc-rfp-001",),
            body=("運用体制、ESG、リスク管理について既存資料に基づく回答案を作成しました。",),
            audit_events=self.audit.all(),
        )
        self._drafts.append(draft)
        self.audit.record("investment.draft_generated", "draft", artifact_type="rfp_response")
        return draft

    def marketing_material_check(self, user: IndustryUser, prompt: str) -> IndustryDraft:
        self._regulated_query_count += 1
        self._disclosure_inconsistency_count += 1
        self._marketing_material_review_count += 1
        risk = self.risk_policy.evaluate(self.profile.risk_policy, prompt)
        citations = self._approved_citations(
            user,
            "FUND-001_交付目論見書_2025",
            "FUND-001_月報_2025-05",
            "コンプライアンス規程_販売資料",
        )
        draft = IndustryDraft(
            artifact_type="marketing_material_comment",
            compliance_review_status="pending",
            reviewer_group="compliance_reviewers",
            source_document_ids=("FUND-001_交付目論見書_2025", "FUND-001_月報_2025-05"),
            source_citations=citations,
            disclosure_evidence_ids=("disc-marketing-001",),
            body=(
                "過去実績が将来成果を保証するように読める表現を修正してください。",
                "performance_period と risk disclosure の根拠不足があります。",
            ),
            audit_events=self.audit.all(),
        )
        self._drafts.append(draft)
        self.audit.record(
            "investment.marketing_material_check",
            "review_required",
            framework_decision=risk.decision,
            matched_rules=risk.matched_rules,
        )
        return draft

    def monthly_commentary_draft(self, user: IndustryUser, prompt: str) -> IndustryDraft:
        citations = self._approved_citations(
            user,
            "FUND-001_月報_2025-05",
            "パフォーマンス要因分析_2025-05",
            "リスク管理体制",
            "運用会議メモ_2025-05",
        )
        draft = IndustryDraft(
            artifact_type="monthly_commentary",
            compliance_review_status="pending",
            reviewer_group="compliance_reviewers",
            source_document_ids=(
                "FUND-001_月報_2025-05",
                "パフォーマンス要因分析_2025-05",
                "リスク管理体制",
            ),
            source_citations=citations,
            disclosure_evidence_ids=("disc-monthly-001",),
            body=(
                "当月の市場環境、パフォーマンス要因、プラス寄与・マイナス寄与を記載します。",
                "過去実績は将来成果を保証しない旨を明記します。",
            ),
            audit_events=self.audit.all(),
        )
        self._drafts.append(draft)
        self.audit.record("investment.draft_generated", "draft", artifact_type="monthly_commentary")
        return draft

    def compliance_rule_question(self, user: IndustryUser, question: str) -> IndustryAnswer:
        self._regulated_query_count += 1
        citations = self._approved_citations(
            user, "コンプライアンス規程_販売資料", "社内規程_広告審査"
        )
        self.audit.record("investment.compliance_rule_question", "answered", user=user.user_id)
        return IndustryAnswer(
            status="ok",
            text=(
                "過去実績を表示する場合は、対象期間、基準日、手数料控除の有無、"
                "将来の成果を保証しない旨を明記する必要があります。最終判断は担当部署レビューが必要です。"
            ),
            citations=citations,
            risk_gate="compliance_rule_question",
            review_required=True,
            audit_events=self.audit.all(),
        )

    def confidential_acl_query(self, user: IndustryUser, question: str) -> IndustryAnswer:
        for document_id in ("FUND-002_運用会議メモ", "FUND-002_銘柄調査メモ"):
            doc = self.documents[document_id]
            if not self._accessible(user, doc):
                self.audit.record("investment.acl_denied", "denied", resource_id=document_id)
        return IndustryAnswer(
            status="no_access",
            text="権限のある範囲には該当情報がありません。",
            citations=(),
            risk_gate="confidential_fund_acl",
            blocked=True,
            audit_events=self.audit.all(),
        )

    def dashboard(self, user: IndustryUser) -> IndustryDashboard:
        if not user.admin:
            self.audit.record("investment.dashboard", "denied", user=user.user_id)
            return IndustryDashboard(metrics={}, audit_events=self.audit.all())
        metrics = {
            "industry_profile_id": self.profile.industry_id,
            "regulated_query_count": self._regulated_query_count,
            "advice_boundary_trigger_count": self._advice_boundary_trigger_count,
            "compliance_review_pending_count": sum(
                1 for draft in self._drafts if draft.compliance_review_status == "pending"
            ),
            "compliance_gate_block_count": self._compliance_gate_block_count,
            "disclosure_inconsistency_count": self._disclosure_inconsistency_count,
            "rfp_response_draft_count": sum(
                1 for draft in self._drafts if draft.artifact_type == "rfp_response"
            ),
            "ddq_response_draft_count": sum(
                1 for draft in self._drafts if draft.artifact_type == "ddq_response"
            ),
            "marketing_material_review_count": self._marketing_material_review_count,
            "inquiry_response_time_reduction": 0,
            "frequently_referenced_documents": (
                "FUND-001_交付目論見書_2025",
                "FUND-001_月報_2025-05",
            ),
            "obsolete_document_candidates": ("FUND-001_旧販売用資料",),
        }
        self.audit.record("investment.dashboard", "viewed", user=user.user_id)
        return IndustryDashboard(metrics=metrics, audit_events=self.audit.all())
