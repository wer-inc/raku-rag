# Feature Specification: Investment Management / Mutual Fund Knowledge RAG (Solution Layer)

**Feature Branch**: `006-investment-management-mutual-fund-rag`

**Created**: 2026-06-19

**Status**: Draft

**Input**: 投資運用会社・投資信託会社・資産運用部門向けの Investment Management / Mutual Fund Knowledge RAG。ファンド関連資料、目論見書、運用報告書、月報、販売用資料、投資ガイドライン、コンプライアンス規程、運用会議メモ、RFP / DDQ、照会対応履歴、リスクレポート、ESG 資料などを取り込み、社内担当者が根拠付きで検索・調査・資料ドラフト・照会回答・レビューを行える AI アシスタントを提供する。

## Relationship to Base Platform and Framework

本 spec は **投資運用会社・投資信託会社向け solution layer** であり、汎用 RAG 基盤 `001-rag-platform` と共通 framework `010-industry-solution-framework` の上に構築する。

### 001-rag-platform = Base RAG Platform

以下の基盤機能は **再定義せず再利用**する。

- tenant isolation / tenant_id を最上位境界とするマルチテナント分離
- ACL / deny-by-default / retrieval pre-filter
- ingestion
- retrieval
- answer generation
- citation / used_chunks / traceability
- groundedness / insufficient evidence behavior
- evaluation
- cost tracking
- audit log
- visual RAG
- parser abstraction
- no-train provider configuration / provider governance

### 010-industry-solution-framework = Industry Solution Framework

006 は 010 の以下を利用する。

- IndustryProfile
- MetadataSchema / MetadataFieldDefinition
- DocumentTypeDefinition
- EntityTypeDefinition
- RiskPolicy / RiskDecision / FinancialRiskDecision
- RequiredEvidencePolicy
- RegulatedActivityPolicy
- AdviceBoundaryPolicy
- DisclosureEvidencePolicy
- ComplianceReviewPolicy
- MarketingMaterialPolicy
- RecordRetentionPolicy
- ApprovalPolicy
- ACLMappingPolicy
- DraftArtifact / RegulatedDraftArtifact
- DraftArtifactTypeDefinition
- DraftReviewPolicy
- WorkflowDefinition
- KPIDefinition
- DashboardWidgetDefinition
- GovernanceProfile / NoTrainPolicy
- AuditEventDefinition
- EvaluationProfile

### 006-investment-management-mutual-fund-rag = Investment Management Solution Layer

006 が新たに定義するのは、投資運用・投資信託会社向けの metadata、fund knowledge workflows、RFP / DDQ workflows、marketing material checks、compliance search、regulated query gate、DisclosureEvidence、RegulatedDraftArtifact、dashboard、PoC KPI である。

`002-manufacturing-field-knowledge-rag` と `003-real-estate-property-management-rag` は変更しない。

### Product / Governance Overlay

no-train policy、audit coverage、AI governance explanation、financial AI governance notes、provider governance status を扱う横断レイヤー。これは 001 を再定義する新しい RAG 基盤ではなく、001 / 010 / 006 にまたがる製品・ガバナンス上の説明レイヤーとして扱う。

## Regulatory Context

This spec records regulatory context for product design only. It does not provide legal interpretation, compliance certification, or final regulatory judgment.

References:
- 金融庁「AIディスカッションペーパー（第1.1版）の公表について」(2026-03-03): https://www.fsa.go.jp/news/r7/sonota/20260303/aidp.html
- 金融庁「金融商品取引業者等向けの総合的な監督指針」(2026-05): https://www.fsa.go.jp/common/law/guide/kinyushohin.pdf
- 金融庁「顧客本位の業務運営について」: https://www.fsa.go.jp/policy/kokyakuhoni/kokyakuhoni.html

Design implication:
- 金融業界での AI 利用は、risk management、governance、investor/customer protection、explainability、record retention、human review を強く意識する。
- 006 は社内業務支援に限定し、投資助言・売買推奨・個別顧客への適合性判断・法令/規制判断・開示資料承認を自動確定しない。

## Purpose

投資運用会社・投資信託会社・資産運用部門が、以下の業務を安全に支援できる AI assistant を提供する。

- ファンド情報・根拠文書の検索
- 目論見書・約款・運用報告書・月報・販売用資料の確認
- 投資ガイドライン・コンプライアンス規程の検索
- RFP / DDQ 回答案の作成
- 販売会社・社内照会への回答 draft 作成
- 月報コメント・運用報告コメント draft 作成
- 販売用資料・説明資料の根拠整合チェック
- 未回答・頻出質問・古い文書・regulated query・compliance review backlog の可視化

この feature は、投資助言 AI、売買推奨 AI、個別顧客への勧誘 AI、適合性判断 AI ではない。

## Target Users

- ファンドマネージャー
- アナリスト
- プロダクト担当
- 投信商品企画担当
- クライアントレポーティング担当
- RFP / DDQ 担当
- コンプライアンス担当
- リスク管理担当
- 営業支援 / 販売会社対応担当
- 法務担当
- 運用企画 / オペレーション担当
- 管理者 / 情報システム担当

## MVP Scope

### In Scope

- PDF / DOCX / XLSX / CSV / HTML / 画像 / スキャン PDF を取り込める。
- 目論見書、交付目論見書、請求目論見書、運用報告書、月次レポート、週次レポート、販売用資料、商品概要資料、約款、投資信託約款、投資ガイドライン、コンプライアンス規程、社内規程、運用会議メモ、銘柄調査メモ、RFP、DDQ、照会回答履歴、リスクレポート、ESG 資料を扱える。
- ファンド ID、ファンド名、ISIN、協会コード、アセットクラス、投資対象、ベンチマーク、為替ヘッジ、信託報酬、リスク分類、販売会社、資料種別、承認状態、有効日などの金融 metadata を付与できる。
- 社内担当者が自然言語で質問し、根拠付き回答を得られる。
- 根拠が不足する場合は推測回答をしない。
- 投資助言、売買推奨、個別顧客への適合性判断、法令判断、規制判断に該当しうる質問は high-risk / regulated query として扱う。
- high-risk / regulated query では、approved かつ effective_date が有効な文書引用がない限り断定回答しない。
- 販売用資料、月報コメント、運用報告書コメント、RFP / DDQ 回答、販売会社向け回答、顧客向け説明文は必ず DraftArtifact として生成し、コンプライアンスまたは責任者レビューを前提にする。
- 管理者は未回答質問、低評価回答、頻出質問、よく参照される文書、古い文書候補、regulated query 数、advice boundary trigger 数、compliance review pending 数、PoC KPI を確認できる。
- 顧客データは標準ではモデル学習・横断改善・別テナント向け改善に利用しない。

### Out of Scope

- 投資助言の自動提供。
- 売買推奨の自動確定。
- ポートフォリオ運用判断の自動化。
- 注文執行。
- 個別顧客への適合性判断。
- 法令・規制判断の最終判断。
- 販売用資料・開示資料の自動承認。
- コンプライアンスレビューの完全自動化。
- 目論見書など法定開示文書の自動確定。
- 顧客向けチャットでの個別投資相談。
- 入出金・口座・取引管理。
- 電子署名。
- フル DMS / 任意版 rollback。
- 音声 RAG。
- 動画 RAG。

## User Scenarios & Testing

### User Story IM-1 - ファンド情報・契約/開示条件の根拠付き確認 (Priority: P1)

社内担当者がファンド名、ファンド ID、ISIN、資料種別、条件などで質問すると、目論見書、約款、運用報告書、月報、商品概要資料、社内規程などの根拠付きで回答を得られる。根拠が不足する場合は推測回答しない。

Examples:
- このファンドの信託報酬、主要投資対象、為替ヘッジ方針を最新目論見書から教えて。
- ベンチマークと投資対象資産はどこに記載されていますか。
- このファンドのリスク分類と手数料を根拠付きで確認したい。

Independent test:
- approved かつ有効な交付目論見書、請求目論見書、約款を取り込み、ファンド ID / ISIN / document_type で質問した時に、該当 citation と as-of / effective date を含む回答が返る。
- 根拠が draft / obsolete のみの場合は `insufficient_evidence` または `review_required` を返す。

### User Story IM-2 - RFP / DDQ 回答案ドラフト (Priority: P1)

RFP / DDQ 担当者が質問票を投入すると、既存 DDQ、運用体制資料、コンプライアンス資料、リスク管理資料、ESG 資料から根拠付き回答案を DraftArtifact として生成できる。

Examples:
- この RFP の運用体制に関する質問に、既存資料から回答案を作って。
- ESG 体制に関する DDQ 回答を過去回答と最新方針から更新して。

Independent test:
- RFP / DDQ 回答案が `artifact_type=rfp_response` または `ddq_response`、`status=draft`、source citations 付きで生成され、自動 approved にならない。

### User Story IM-3 - 販売用資料・説明資料の整合チェック (Priority: P1)

プロダクト担当またはコンプライアンス担当が販売用資料や説明資料をチェックすると、目論見書、約款、商品概要、リスク開示、手数料、運用方針、パフォーマンス期間との矛盾や根拠不足を検出できる。

Examples:
- この販売用資料の表現は、目論見書・交付資料と矛盾していないか確認して。
- パフォーマンス説明の期間と根拠資料を確認して。

Independent test:
- MarketingMaterialPolicy と DisclosureEvidencePolicy により、資料 draft の statement ごとに source consistency、risk disclosure、performance claim、approved/effective source の有無が判定される。

### User Story IM-4 - 月報・運用報告コメントドラフト (Priority: P2)

クライアントレポーティング担当が、運用方針、パフォーマンス要因、リスクレポート、過去月報、運用会議メモを根拠に、月報コメントや運用報告書コメントの draft を作成できる。

Examples:
- このファンドの月報コメントのドラフトを、運用方針とパフォーマンス要因に基づいて作って。
- 直近月の要因分析を、内部メモとリスクレポートから要約して。

Independent test:
- DraftArtifact は `status=draft` で作成され、パフォーマンス・リスク・投資方針の記述に根拠文書と時点が紐づく。

### User Story IM-5 - コンプライアンス規程・投資ガイドライン確認 (Priority: P2)

運用担当、コンプライアンス担当、リスク管理担当が、投資ガイドライン、社内規程、コンプライアンス規程、リスク制限、運用会議メモを検索し、該当箇所と根拠を確認できる。

Examples:
- このファンドで投資制限・ガイドライン違反になりそうな記述や条件はある？
- デリバティブ利用方針はどこに記載されていますか。

Independent test:
- regulated query として RiskPolicy が発火し、approved/effective source がない場合は断定回答せず、review_required を返す。

### User Story IM-6 - 管理ダッシュボード (Priority: P3)

管理者が、未回答、低評価、頻出質問、よく参照される文書、古い文書候補、regulated query 数、advice boundary trigger 数、compliance review pending 数、PoC KPI を確認できる。

Independent test:
- audit、feedback、DraftArtifact、compliance review、RiskDecision、DisclosureEvidence から KPI が集計され、権限のある管理者だけが閲覧できる。

## Edge Cases

- ファンド名だけでは share class / currency / hedged class が一意に決まらない場合、推測せず追加確認または候補提示を行う。
- 最新目論見書と旧販売用資料の記述が矛盾する場合、latest approved source を優先し、矛盾を明示する。
- パフォーマンス実績、利回り、ランキング、リスク、手数料、投資方針、ESG、運用体制の記述は as-of date と source citation を必須にする。
- 銘柄調査メモや運用会議メモは内部参考情報として扱い、顧客向け正式根拠や投資判断の自動確定に使わない。
- 投資助言・売買推奨・個別顧客への適合性判断に近い質問は advice boundary として block / review_required / disclaimer 付きにする。
- 法令・規制判断は自動確定せず、コンプライアンスまたは法務 review required とする。
- obsolete / draft 文書しか根拠がない場合、正式根拠として断定回答に使わない。
- 権限のないファンド、社内メモ、顧客情報、取引情報、DraftArtifact、KPI は検索結果・回答・引用・dashboard に表示しない。
- OCR 信頼度が低い文書は evidence confidence を下げ、必要に応じて根拠不足とする。
- tombstone 済み文書、撤回済み資料、差し替え済み資料は検索・回答・citation・cache・dashboard から即時除外する。

## Requirements

> 記法: 本 spec 固有要件は **FR-IM-###**。001 の基盤再利用は `[base:001]`、010 の framework 再利用は `[framework:010]` と明記する。

### Functional Requirements - Scope / Base Reuse

- **FR-IM-001**: システムは `001-rag-platform` を基盤として利用し、tenant isolation、ACL、ingestion、retrieval、answer、citation、groundedness、evaluation、cost、audit、visual RAG、parser abstraction、no-train provider config を再定義してはならない。`[base:001]`
- **FR-IM-002**: システムは `010-industry-solution-framework` を利用し、IndustryProfile、MetadataSchema、RiskPolicy、RequiredEvidencePolicy、DraftArtifact、KPI、Dashboard、ACLMapping、GovernanceProfile、Financial / Regulated extension を再利用しなければならない。`[framework:010]`
- **FR-IM-003**: 006 は投資運用会社・投資信託会社向け社内業務支援に限定し、個人投資家への直接助言・勧誘・適合性判断を MVP 範囲に含めてはならない。
- **FR-IM-004**: 006 は `002-manufacturing-field-knowledge-rag` と `003-real-estate-property-management-rag` を変更してはならない。

### Functional Requirements - Document Ingestion / Metadata

- **FR-IM-010**: システムは PDF / DOCX / XLSX / CSV / HTML / 画像 / スキャン PDF を取り込めなければならない。
- **FR-IM-011**: システムは、目論見書、交付目論見書、請求目論見書、運用報告書、月次レポート、週次レポート、販売用資料、商品概要資料、約款、投資信託約款、投資ガイドライン、コンプライアンス規程、社内規程、運用会議メモ、銘柄調査メモ、RFP、DDQ、照会回答履歴、リスクレポート、ESG 資料を扱えなければならない。
- **FR-IM-012**: InvestmentManagementDocumentMetadata は Document / Chunk metadata として付与され、retrieval filter、risk policy、DisclosureEvidence、citation、dashboard 集計で利用できなければならない。
- **FR-IM-013**: InvestmentManagementDocumentMetadata は少なくとも `fund_id`, `fund_name`, `fund_code`, `share_class_id`, `isin`, `association_code`, `asset_class`, `investment_region`, `investment_target`, `investment_strategy`, `benchmark`, `currency_hedge_policy`, `currency_hedge`, `fee_type`, `trust_fee`, `risk_category`, `risk_classification`, `target_investor_category`, `distribution_partner_id`, `distributor_id`, `document_type`, `document_period`, `report_date`, `approval_status`, `approval_source`, `approved_by`, `approved_at`, `effective_date`, `as_of_date`, `obsolete_at`, `superseded_by`, `performance_period`, `disclosure_category`, `compliance_risk_category`, `compliance_category`, `marketing_material_category`, `advice_boundary_category`, `legal_risk_category`, `regulated_activity_category`, `confidential_data_category`, `personal_data_category`, `owner_department`, `access_scope`, `no_train_policy_ref`, `retention_policy_ref` を保持しなければならない。`association_code` / `fund_code`, `currency_hedge` / `currency_hedge_policy`, `risk_classification` / `risk_category`, `distributor_id` / `distribution_partner_id` は顧客・販売会社データとの互換 alias として扱う。
- **FR-IM-014**: `document_type` は少なくとも `prospectus`, `statutory_prospectus`, `summary_prospectus`, `delivered_prospectus`, `requested_prospectus`, `trust_deed`, `fund_report`, `monthly_report`, `weekly_report`, `marketing_material`, `product_summary`, `investment_guideline`, `compliance_manual`, `compliance_policy`, `internal_policy`, `investment_committee_minutes`, `research_memo`, `security_research_memo`, `rfp`, `ddq`, `inquiry_response`, `inquiry_history`, `risk_report`, `esg_report`, `esg_document`, `client_report`, `sales_company_notice`, `faq` を識別できなければならない。`delivered_prospectus` / `statutory_prospectus`, `requested_prospectus` / `summary_prospectus`, `compliance_policy` / `compliance_manual`, `security_research_memo` / `research_memo`, `inquiry_history` / `inquiry_response`, `esg_document` / `esg_report` は互換 alias として扱う。
- **FR-IM-015**: XLSX / CSV / HTML table は sheet / row / column / cell_range / html selector などを citation に利用できる形で保持しなければならない。

### Functional Requirements - Grounded Answer / Regulated Gate

- **FR-IM-020**: システムは自然言語質問に対し、001 の retrieval / answer / groundedness / citation を再利用し、ファンド・資料・規程・照会履歴の文脈に沿った根拠付き回答を返せなければならない。
- **FR-IM-021**: 根拠が不足する場合、システムは推測回答をせず `insufficient_evidence` を返さなければならない。
- **FR-IM-022**: システムは high-risk / regulated query を判定しなければならない。以下に関わる質問は high-risk / regulated とする: 投資助言、売買推奨、個別顧客への適合性判断、ポートフォリオ運用判断の確定、法令判断、規制判断、販売用資料の承認、開示資料の確定、手数料・リスク・利回り・過去実績・投資方針・ESG・運用体制に関する顧客向け断定、苦情・紛争・当局対応。
- **FR-IM-023**: high-risk / regulated query では、`approval_status=approved` かつ `effective_date` が有効な文書引用が無い限り断定回答してはならない。
- **FR-IM-024**: obsolete / draft 文書を正式根拠として断定回答に使ってはならない。必要に応じて obsolete warning または draft warning を表示する。
- **FR-IM-025**: AdviceBoundaryPolicy は投資助言・売買推奨・適合性判断に近い intent を検出し、prohibited output を block し、allowed output として根拠文書の要約、内部 draft、review_required、insufficient_evidence を返せなければならない。
- **FR-IM-026**: RegulatedActivityPolicy は regulated activity を判定し、restricted / prohibited action では human review, escalation, disclaimer, audit を要求できなければならない。
- **FR-IM-027**: FinancialRiskDecision は advice boundary、regulated activity、marketing material、compliance review required の判定結果と理由、policy_version を保持しなければならない。

### Functional Requirements - Disclosure Evidence / Marketing Material Check

- **FR-IM-030**: DisclosureEvidencePolicy は customer-facing / sales-facing / regulator-facing artifact に対して required source document types、latest approved source、有効日、citation requirement、contradiction check を定義できなければならない。
- **FR-IM-031**: システムは販売用資料・商品概要資料・説明資料の文言を、目論見書、約款、商品概要、リスク開示、手数料、運用方針、ベンチマーク、performance period と照合できなければならない。
- **FR-IM-032**: MarketingMaterialPolicy は source consistency、risk disclosure、prohibited expression rules、performance claim rules、review_required、citation_required を適用できなければならない。
- **FR-IM-033**: 過去実績、利回り、リスク、手数料、投資方針、運用体制、ESG、パフォーマンス要因に関する記述は、根拠文書、as_of_date、effective_date、performance_period を追跡可能にしなければならない。
- **FR-IM-034**: Contradiction check result は statement、matched source、contradiction type、severity、recommended action、audit_log_ref を保持しなければならない。

### Functional Requirements - Workflows

- **FR-IM-040**: `fund-question` workflow はファンド情報、目論見書、約款、月報、運用報告書、リスクレポートを根拠付きで回答できなければならない。
- **FR-IM-041**: `rfp-response-draft` workflow は RFP 質問に対し、既存 RFP / DDQ、運用体制資料、コンプライアンス資料、リスク管理資料、ESG 資料から回答 draft を生成できなければならない。
- **FR-IM-042**: `ddq-response-draft` workflow は DDQ 質問に対し、過去回答と最新 approved source の差分を反映した回答 draft を生成できなければならない。
- **FR-IM-043**: `inquiry-reply-draft` workflow は販売会社または社内照会への回答 draft を生成できなければならない。
- **FR-IM-044**: `marketing-material-check` workflow は販売用資料や説明資料の整合性、根拠不足、risk disclosure、prohibited expressions を検出できなければならない。
- **FR-IM-045**: `monthly-commentary-draft` workflow は運用方針、パフォーマンス要因、リスクレポート、過去月報、運用会議メモを根拠に月報コメント draft を生成できなければならない。
- **FR-IM-046**: `compliance-rule-question` workflow はコンプライアンス規程、社内規程、投資ガイドライン、リスク制限に関する根拠付き回答を返し、法令・規制判断を自動確定してはならない。

### Functional Requirements - DraftArtifact / Compliance Review

- **FR-IM-050**: 販売用資料、月報コメント、運用報告書コメント、RFP / DDQ 回答、販売会社向け回答、顧客向け説明文、FAQ、internal note は必ず InvestmentDraftArtifact または RegulatedDraftArtifact として作成し、初期状態を `draft` としなければならない。
- **FR-IM-051**: DraftArtifact は自動的に `approved` または `compliance_approved` になってはならない。
- **FR-IM-052**: InvestmentDraftArtifact の `artifact_type` は少なくとも `rfp_response`, `ddq_response`, `inquiry_reply`, `marketing_material_comment`, `monthly_commentary`, `fund_report_commentary`, `compliance_check_memo`, `fund_condition_summary`, `faq`, `internal_note` を含まなければならない。
- **FR-IM-053**: InvestmentDraftArtifact は `artifact_id`, `artifact_type`, `status`, `compliance_review_status`, `created_by`, `reviewer_id` または `reviewer_group`, `assigned_at`, `reviewed_at`, `review_comment`, `approval_decision`, `source_citations`, `source_document_ids`, `disclosure_evidence_ids`, `generated_at`, `template_id`, `audit_log_ref`, `retention_policy_ref` を保持しなければならない。
- **FR-IM-054**: ComplianceReviewPolicy は review_required artifact types、reviewer roles、review states、required review fields、audit_required、retention_required を定義できなければならない。
- **FR-IM-055**: DraftArtifact の生成、review assignment、status transition、compliance review transition は audit log 対象でなければならない。

### Functional Requirements - Dashboard / KPI

- **FR-IM-060**: 管理者は未回答質問、低評価回答、頻出質問、よく参照される文書、古い文書候補、regulated query 数、advice boundary trigger 数、compliance review pending 数、PoC KPI を dashboard で確認できなければならない。
- **FR-IM-061**: InvestmentManagementKPI は少なくとも `self_resolution_rate`, `average_time_to_answer`, `grounded_answer_rate`, `insufficient_evidence_rate`, `low_rating_rate`, `unanswered_question_count`, `frequently_referenced_documents`, `obsolete_document_candidates`, `knowledge_gap_topics`, `regulated_query_count`, `advice_boundary_trigger_count`, `regulated_activity_trigger_count`, `compliance_review_pending_count`, `draft_review_completion_rate`, `rfp_response_draft_count`, `ddq_response_draft_count`, `marketing_material_check_count`, `contradiction_detected_count`, `monthly_commentary_draft_count` を含まなければならない。
- **FR-IM-062**: dashboard / KPI は tenant、collection、department、fund、document_type、time range、regulated_activity_category で集計でき、権限のない fund、internal memo、customer data、DraftArtifact、KPI を表示してはならない。

### Functional Requirements - ACL / Access Control

- **FR-IM-070**: 006 は 001 の ACL を利用し、少なくとも `department_id`, `role`, `fund_id`, `fund_code`, `share_class_id`, `asset_class`, `strategy_id`, `distribution_partner_id`, `distributor_id`, `document_type`, `approval_status`, `confidential_data_category`, `personal_data_category`, `regulated_activity_category` を ACL / metadata filter に mapping できなければならない。
- **FR-IM-071**: 権限のないファンド、社内メモ、銘柄調査メモ、RFP / DDQ、顧客情報、取引情報、DraftArtifact、dashboard KPI は retrieval result、answer context、citation、admin API response に含めてはならない。
- **FR-IM-072**: ACL denied、tenant isolation denied は audit log 対象でなければならない。

### Functional Requirements - PII / Confidential Financial Data

- **FR-IM-080**: 個人名、住所、電話番号、メール、口座情報、取引情報、保有商品、顧客属性、適合性情報、照会履歴、苦情履歴は personal data または confidential financial data として分類しなければならない。
- **FR-IM-081**: personal data / confidential financial data は tenant_id、ACL、audit、redaction policy、retention policy の対象にしなければならない。
- **FR-IM-082**: ログ、trace、evaluation data、error output には personal data / confidential financial data を不用意に保存してはならない。
- **FR-IM-083**: dashboard では必要最小限の personal data / confidential financial data のみ表示しなければならない。

### Functional Requirements - No-Train / Governance / Retention

- **FR-IM-090**: 顧客がアップロードした文書、ファンド資料、社内メモ、問い合わせ履歴、回答、引用、DraftArtifact、評価データ、ログは、デフォルトではモデル学習・モデル改善に利用してはならない。
- **FR-IM-091**: opt-in なしに、顧客データを横断的なモデル改善や別テナント向け改善に利用してはならない。
- **FR-IM-092**: provider no-train capability は 001 の provider configuration / contract mode に依存し、006 は tenant policy、opt-in / opt-out、audit、governance status、営業・PoC 説明上の no-train 表示を扱わなければならない。
- **FR-IM-093**: RecordRetentionPolicy は regulated events、DraftArtifact、DisclosureEvidence、review decisions、audit export、tamper evidence、PII redaction、legal hold support を扱えるようにしなければならない。

## Key Entities / Data Model

- **Fund**: `fund_id`, `fund_name`, `fund_code`, `isin`, `association_code`, `asset_class`, `investment_region`, `investment_target`, `strategy_id`, `benchmark`, `currency_hedge_policy`, `currency_hedge`, `risk_category`, `risk_classification`, `status`
- **FundShareClass**: `share_class_id`, `fund_id`, `currency`, `hedged_flag`, `distribution_policy`, `fee_class`, `effective_date`
- **FundDocument**: `document_id`, `fund_id`, `document_type`, `document_period?`, `report_date?`, `approval_status`, `effective_date`, `as_of_date`, `source_uri`
- **InvestmentManagementDocumentMetadata**: document/chunk metadata defined in FR-IM-013
- **ProspectusReference**: `prospectus_id`, `fund_id`, `document_type`, `effective_date`, `approval_status`, `superseded_by`
- **InvestmentGuideline**: `guideline_id`, `fund_id`, `restriction_type`, `limit_value`, `effective_date`, `approval_status`
- **ComplianceRule**: `rule_id`, `category`, `source_document_id`, `effective_date`, `owner_department`, `review_required`
- **RFPCase**: `rfp_id`, `client_or_distributor_ref`, `fund_id`, `question_set`, `response_artifacts`, `status`
- **DDQCase**: `ddq_id`, `fund_id`, `question_set`, `response_artifacts`, `status`
- **InquiryCase**: `inquiry_id`, `source_type`, `fund_id`, `question`, `response_artifact_id`, `status`
- **MarketingMaterialCheck**: `check_id`, `artifact_id`, `source_document_ids`, `contradiction_results`, `review_status`
- **DisclosureEvidence**: `evidence_id`, `artifact_id`, `statement_id`, `source_citations`, `source_document_ids`, `source_as_of_date`, `source_effective_date`, `evidence_status`
- **InvestmentDraftArtifact**: extends DraftArtifact / RegulatedDraftArtifact for 006 artifact types
- **InvestmentDraftReview**: `review_id`, `artifact_id`, `reviewer_id`, `review_state`, `review_comment`, `reviewed_at`, `audit_log_ref`
- **InvestmentComplianceReview**: `compliance_review_id`, `artifact_id`, `reviewer_group`, `review_state`, `required_changes`, `decision`, `audit_log_ref`
- **FinancialRiskDecision**: financial/regulated risk decision defined by 010
- **InvestmentManagementKPI**: KPI values defined in FR-IM-061

## High-Risk / Regulated Query Categories

The following must be treated as high-risk / regulated:

- investment advice
- buy / sell / hold recommendation
- individual customer suitability
- portfolio operation decision finalization
- legal or regulatory judgment
- marketing material approval
- disclosure document finalization
- performance or return claim
- risk or loss claim
- fee / expense claim
- investment policy / guideline compliance claim
- ESG claim
- complaint / dispute / regulator response
- customer personal data disclosure
- confidential trading or holding information disclosure

## Required Evidence and Review Rules

- approved かつ effective_date が有効な文書引用がない限り、high-risk / regulated query に対して断定回答しない。
- latest approved source が必要な document_type では、旧版や obsolete 文書を正式根拠として使わない。
- draft 文書は正式根拠として扱わず、reference / candidate としてのみ利用する。
- 顧客向け資料、販売用資料、月報、運用報告書、RFP / DDQ 回答、販売会社向け回答は DraftArtifact とし、compliance または responsible manager review を前提にする。
- 法令・規制判断、投資助言、売買推奨、適合性判断は自動確定しない。

## Audit Log Events

少なくとも以下を audit log 対象にする。

- document upload / ingest / parse
- InvestmentManagementDocumentMetadata の作成・更新・削除
- approval_status の変更
- external approval metadata の import
- search query
- answer generation
- citation access
- high-risk / regulated query 判定
- advice boundary 判定
- regulated activity 判定
- compliance gate 判定
- insufficient evidence response
- DraftArtifact の生成
- DraftArtifact の review assignment
- DraftArtifact の status transition
- compliance review transition
- DisclosureEvidence の生成
- contradiction check result
- feedback / low rating
- dashboard access
- KPI calculation / export
- ACL denied
- tenant isolation denied
- no-train / retention / provider setting changes
- deletion / tombstone / cache invalidation

## API Candidates

後続 plan で少なくとも以下の API を扱う。

```text
POST /investment/metadata/import
POST /investment/documents/enrich
GET  /investment/funds/{fund_id}/knowledge
POST /investment/workflows/fund-question
POST /investment/workflows/rfp-response-draft
POST /investment/workflows/ddq-response-draft
POST /investment/workflows/inquiry-reply-draft
POST /investment/workflows/marketing-material-check
POST /investment/workflows/monthly-commentary-draft
POST /investment/workflows/compliance-rule-question
GET  /investment/drafts/{artifact_id}
POST /investment/drafts/{artifact_id}/review
POST /investment/drafts/{artifact_id}/compliance-review
GET  /investment/disclosure-evidence/{artifact_id}
GET  /investment/dashboard
GET  /investment/kpi
GET  /investment/audit
GET  /investment/governance/status
```

These may map internally to 010 common APIs such as `/industries/{industry_id}/workflows/{workflow_id}/run`, but domain-friendly `/investment/...` APIs are defined for solution readability.

## Evaluation / Quality Checks

- approved/effective citation coverage for regulated answers
- insufficient evidence behavior for missing approved source
- draft/obsolete source exclusion from definitive answers
- advice boundary trigger accuracy
- regulated activity trigger accuracy
- marketing material contradiction detection
- citation accuracy for PDF / spreadsheet / HTML table sources
- ACL leakage = 0
- tenant isolation leakage = 0
- personal data leakage in logs/evaluation = 0
- no auto-approved AI DraftArtifact
- no auto-approved compliance review
- no-train policy applied by default
- baseline regression for recall@k and citation accuracy

## Success Criteria

- **SC-IM-001**: 投資助言・売買推奨・適合性判断に該当しうる high-risk query では、AI が断定回答や推奨を自動確定しない。
- **SC-IM-002**: 販売用資料・月報・RFP / DDQ 回答などの DraftArtifact は自動 approved にならない。
- **SC-IM-003**: high-risk / regulated query では approved かつ有効な文書引用がない限り断定回答しない。
- **SC-IM-004**: 目論見書・約款・運用方針・手数料・リスク開示と矛盾する資料ドラフトを検出できる。
- **SC-IM-005**: 権限のないファンド・社内メモ・顧客情報・DraftArtifact が検索結果、回答、引用、ダッシュボードに出ない。
- **SC-IM-006**: 根拠不足の場合は `insufficient_evidence` を返す。
- **SC-IM-007**: obsolete / draft 文書を正式根拠として断定回答に使わない。
- **SC-IM-008**: no-train policy が標準で有効である。
- **SC-IM-009**: dashboard で未回答、低評価、頻出質問、古い文書候補、regulated query 数、advice boundary trigger 数、compliance review pending 数を確認できる。
- **SC-IM-010**: PoC KPI を計測できる。

## Non-Goals

- 投資助言の自動提供。
- 売買推奨の自動確定。
- ポートフォリオ運用判断の自動化。
- 注文執行。
- 個別顧客への適合性判断。
- 法令・規制判断の最終判断。
- 販売用資料・開示資料の自動承認。
- コンプライアンスレビューの完全自動化。
- 目論見書など法定開示文書の自動確定。
- 顧客向けチャットでの個別投資相談。
- 入出金・口座・取引管理。
- 電子署名。
- フル DMS / 任意版 rollback。
- 音声 RAG。
- 動画 RAG。

## Clarifications / Open Questions Before `/speckit-plan`

No blocking NEEDS CLARIFICATION for initial spec creation. Before planning, confirm at most:

1. **Customer-facing output boundary**: MVP は完全に社内利用に限定するか、review 済み export のみ顧客向け利用を許すか。
   - Recommended default: MVP は社内利用に限定し、顧客向け利用は reviewed export のみ。
2. **Compliance review workflow**: compliance review states と reviewer roles を全社共通にするか、顧客設定で変えるか。
   - Recommended default: 010 の ComplianceReviewPolicy を共通 contract とし、顧客別に reviewer roles を設定する。
3. **Marketing material check scope**: MVP で販売用資料全体を対象にするか、statement-level consistency check から始めるか。
   - Recommended default: statement-level consistency check から開始する。
4. **RFP / DDQ source priority**: 過去回答と最新 approved source が矛盾した場合の優先順位をどうするか。
   - Recommended default: latest approved source を優先し、過去回答は reference として差分表示する。
5. **Retention policy**: regulated audit / draft / disclosure evidence の保持期間を業界 default にするか、顧客 policy に委譲するか。
   - Recommended default: RecordRetentionPolicy で customer-configurable とし、MVP では policy ref だけ保持する。

## Confirmation

- 006 は `001-rag-platform` を再定義しない。
- 006 は `010-industry-solution-framework` を industry solution framework として利用する。
- 006 は `002-manufacturing-field-knowledge-rag` と `003-real-estate-property-management-rag` を変更しない。
- 006 は投資助言・売買推奨・個別顧客への適合性判断を自動化しない。
