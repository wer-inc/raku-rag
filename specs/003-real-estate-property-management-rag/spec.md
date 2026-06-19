# Feature Specification: Real Estate Property Management Knowledge RAG (Solution Layer)

**Feature Branch**: `003-real-estate-property-management-rag`

**Created**: 2026-06-19

**Status**: Draft

**Input**: 不動産管理会社・賃貸管理部門・PM 業務向けの Real Estate Property Management Knowledge RAG。物件資料、賃貸借契約書、重要事項説明書、管理規約、修繕履歴、点検報告、入居者問い合わせ履歴、オーナー報告書、見積書、請求書、Excel 台帳などを取り込み、担当者が根拠付きで質問・調査・返信ドラフト・報告書ドラフトを作成できる AI アシスタントを提供する。

## Relationship to Base Platform (001-rag-platform)

本 spec は **solution layer** であり、汎用 RAG 基盤 `001-rag-platform` の上に構築する。以下の基盤機能は **再定義せず再利用**する（参照のみ。詳細は `specs/001-rag-platform/spec.md`）。

- tenant isolation / tenant_id を最上位境界とするマルチテナント分離
- ACL（deny-by-default, retrieval pre-filter）と署名付き claims による権限評価
- citation / used_chunks / traceability
- groundedness（2 段階ゲート、根拠不足時は推測しない）
- ingestion / parser abstraction / chunking / embedding / retrieval / answer / deletion(tombstone)
- evaluation gate / cost budget / observability / audit log 方針
- visual RAG（OCR / layout / visual citation / optional captioning）
- provider governance / no-train capability / contract mode 方針

本 spec が新たに定義するのは **不動産管理・賃貸管理 PM 業務固有**のメタデータ、物件・契約・修繕・問い合わせワークフロー、DraftArtifact、risk gate、dashboard、PoC KPI、governance 表示である。`002-manufacturing-field-knowledge-rag` は参照せず、変更しない。

## Relationship to Industry Solution Framework (010-industry-solution-framework)

本 spec は `010-industry-solution-framework` の **Real Estate Property Management IndustryProfile** として定義する。010 の共通抽象を再定義せず、以下のようにマッピングする。

- RealEstateDocumentMetadata → 010 `MetadataSchema` / `MetadataFieldDefinition`
- 不動産 document_type → 010 `DocumentTypeDefinition`
- Property / Building / Unit / Owner / Occupant / LeaseContract / RepairCase 等 → 010 `EntityTypeDefinition`
- contract / legal / financial / personal data high-risk 判定 → 010 `RiskPolicy` / `RequiredEvidencePolicy`
- approved / effective document citation requirement → 010 `ApprovalPolicy` / `RequiredEvidencePolicy`
- occupant_reply / owner_report / repair_report / move_out_checklist / restoration_explanation / faq → 010 `DraftArtifactTypeDefinition`
- RealEstateDraftReview → 010 `DraftReviewPolicy`
- RealEstateKPI / dashboard → 010 `KPIDefinition` / `DashboardWidgetDefinition`
- branch_id / department_id / property_id / building_id / unit_id / owner_id / document_type / approval_status / personal_data_category → 010 `ACLMappingPolicy`

010 は共通 contract と profile registry を提供するだけであり、不動産管理固有の契約・修繕・入居者対応 semantics は本 003 spec に残す。

## Architecture Overview

1. **001-rag-platform = Base RAG Platform**
   tenant isolation、ACL、ingestion、retrieval、answer、citation、groundedness、evaluation、cost、audit、visual RAG、parser abstraction を提供する。

2. **010-industry-solution-framework = Industry Solution Framework**
   IndustryProfile、MetadataSchema、RiskPolicy、RequiredEvidencePolicy、DraftArtifact、KPI、Dashboard、ACLMapping、GovernanceProfile を提供する。

3. **003-real-estate-property-management-rag = Real Estate Solution Layer**
   不動産管理メタデータ、物件・契約・修繕・問い合わせワークフロー、RealEstateDraftArtifact、risk gate、dashboard、PoC KPI を提供する。

4. **Product / Governance Overlay = Cross-cutting Product Governance**
   no-train policy、audit coverage、AI governance explanation、ISMAP readiness memo、PoC readiness、provider governance status を扱う横断レイヤー。これは 001 を再定義する新しい RAG 基盤ではなく、001 / 010 / 003 にまたがる製品・ガバナンス上の説明レイヤーとして扱う。

## Terminology

- `tenant_id` は 001 基盤上の **SaaS 顧客テナント**を意味する。
- 不動産の「入居者」は `tenant` と呼ばず、**Occupant / Lessee / Renter** と表現する。
- 「物件」は Property、「建物」は Building、「部屋・区画」は Unit と表現する。
- 「オーナー」は Owner、「管理会社・賃貸管理部門の担当者」は staff / property manager / PM staff と表現する。

## Clarifications

### Session 2026-06-19

- 本 feature の MVP は「不動産業界全般」ではなく、**不動産管理会社・賃貸管理部門・PM 業務**に絞る。
- `001-rag-platform` の基盤機能は再定義しない。003 は不動産管理 solution layer のみを定義する。
- `002-manufacturing-field-knowledge-rag` は変更しない。
- No-train / governance は 002 と同じ責務境界を踏襲する。003 は tenant policy、opt-in / opt-out、audit、governance status、営業・PoC 説明上の no-train 表示を扱い、provider no-train capability の検証は 001 側に依存する。
- 未解決の clarification は現時点では無し。

## User Scenarios & Testing *(mandatory)*

### User Story RE-1 - 物件・契約条件の根拠付き確認 (Priority: P1)

賃貸管理担当者が物件名、部屋番号、契約 ID、入居者名、契約条件などで質問すると、賃貸借契約書、重要事項説明書、管理規約、社内マニュアルなどの根拠付きで回答を得られる。根拠が不足する場合は推測回答しない。

**Why this priority**: PM 業務の中核である契約条件確認・問い合わせ対応の前提。契約条件や費用負担は誤回答リスクが高く、citation と risk gate が揃って初めて業務利用できる。

**Independent Test**: 承認済みの賃貸借契約書・重要事項説明書・管理規約・社内マニュアルを取り込み、(a) 更新料・ペット可否・駐車場条件に対して引用付き回答、(b) 根拠が無い条件質問では `insufficient_evidence` を返すことで検証できる。

**Acceptance Scenarios**:

1. **Given** 契約書・重要事項説明書・管理規約が取り込み済み, **When** 担当者が「この部屋の更新料はいくらですか？」と質問する, **Then** approved かつ有効な文書引用、契約 ID、unit_id、該当条項または該当セル参照を含む回答を返す。
2. **Given** 原状回復負担範囲が文書に記載されている, **When** 担当者が「原状回復の負担範囲はどこに書いてありますか？」と質問する, **Then** 断定内容と引用箇所を対応付け、過去対応履歴のみを正式根拠として扱わない。
3. **Given** ペット飼育可否に関する根拠が draft 文書にしかない, **When** 担当者が質問する, **Then** draft 文書を正式根拠にせず、必要に応じて `insufficient_evidence` または draft warning を返す。
4. **Given** 権限のない物件または部屋の契約文書, **When** 担当者が質問する, **Then** 当該文書は retrieval result、answer context、citation に含まれない。

---

### User Story RE-2 - 修繕・設備トラブル調査 (Priority: P1)

修繕・メンテナンス担当者が物件、設備、症状、修繕カテゴリを入力すると、過去の修繕履歴、点検報告、見積書、請求書、対応履歴から類似事例と対応状況を確認できる。

**Why this priority**: 管理会社の問い合わせ対応・オーナー報告・修繕判断の速度に直結する。契約条件確認と並ぶ MVP の主要価値。

**Independent Test**: 修繕履歴、点検報告、見積書、請求書、問い合わせ履歴を取り込み、物件・設備・症状クエリから過去対応、費用、対応中/完了状態、引用が返ることで検証できる。

**Acceptance Scenarios**:

1. **Given** 水漏れ対応履歴がある物件, **When** 担当者が「この物件で過去に水漏れ対応はありましたか？」と質問する, **Then** RepairCase / MaintenanceRequest と引用文書を返し、過去事例として表示する。
2. **Given** エアコン故障の見積書・請求書・対応履歴, **When** 担当者が「エアコン故障の過去対応と費用を教えてください」と質問する, **Then** 金額と根拠文書を返すが、費用負担判断は high-risk として正式判断を自動確定しない。
3. **Given** 点検報告書が複数ある設備, **When** 担当者が「この設備の点検履歴をまとめてください」と質問する, **Then** 点検日、報告書、異常有無、引用を一覧化する。
4. **Given** 権限外のオーナーまたは物件に紐づく修繕履歴, **When** 担当者が調査する, **Then** 結果・引用・dashboard drilldown に出さない。

---

### User Story RE-3 - 入居者・オーナー向け返信ドラフト (Priority: P2)

担当者が問い合わせ内容を入力すると、契約書・管理規約・過去対応履歴を根拠にした入居者またはオーナー向け返信ドラフトを生成できる。生成物は必ず RealEstateDraftArtifact とし、人間レビューを前提にする。

**Why this priority**: 問い合わせ対応時間を削減するが、顧客への正式回答は誤回答リスクが高いため、draft と review gate が不可欠。

**Independent Test**: 入居者からの水漏れ問い合わせ、オーナー向け修繕見積説明、原状回復費用説明のドラフトを生成し、すべて `status=draft`、source_citations 付き、自動 approved にならないことを検証する。

**Acceptance Scenarios**:

1. **Given** 入居者問い合わせと過去対応履歴, **When** 担当者が「入居者への水漏れ対応返信を作ってください」と依頼する, **Then** `artifact_type=occupant_reply`、`status=draft`、引用付きの返信案を生成する。
2. **Given** 修繕見積と点検結果, **When** 担当者が「オーナー向けに修繕見積の説明文を作ってください」と依頼する, **Then** `artifact_type=owner_report` または `repair_report` の draft を生成し、金額請求・費用負担判断は review required と表示する。
3. **Given** 原状回復費用に関する問い合わせ, **When** 担当者が説明案を生成する, **Then** high-risk として approved・有効引用を必要とし、根拠不足なら断定しない draft を作成する。
4. **Given** AI が作成した draft, **When** 生成完了する, **Then** 自動的に `approved` にならず、人間 review が必要な状態で保存される。

---

### User Story RE-4 - オーナー報告・修繕報告ドラフト (Priority: P2)

担当者が修繕履歴、見積、点検結果をもとに、オーナー向け報告書や修繕報告書のドラフトを作れる。

**Why this priority**: PM 業務の報告書作成負荷を削減する。正式提出物になる可能性があるため、引用・audit・review が必要。

**Independent Test**: 修繕履歴、見積、請求書、点検報告から owner_report / repair_report draft を生成し、根拠引用、未確定事項、review 状態が保持されることで検証できる。

**Acceptance Scenarios**:

1. **Given** 修繕履歴・見積書・点検報告が取り込み済み, **When** 担当者がオーナー報告 draft を生成する, **Then** 修繕内容、原因、費用、今後対応案を引用付きでまとめる。
2. **Given** 費用負担または請求に関わる記述, **When** 報告書 draft を生成する, **Then** high-risk として専門家/担当者 review が必要であることを表示する。
3. **Given** 参照文書の一部が obsolete, **When** 報告書 draft を生成する, **Then** obsolete 文書を正式根拠として断定せず、warning または根拠不足を表示する。

---

### User Story RE-5 - 契約更新・退去・原状回復チェックリスト (Priority: P2)

契約更新、退去、原状回復、鍵返却、立会い、精算などの業務に必要な確認項目を、承認済み文書に基づいて checklist draft として生成できる。

**Why this priority**: 更新・退去・精算はミスの影響が大きい PM 業務。自動確定ではなく checklist draft として支援することで安全に効率化できる。

**Independent Test**: 承認済み契約書、原状回復資料、社内マニュアルから renewal_checklist / move_out_checklist / restoration_explanation draft を生成し、approved・有効引用が無い項目は断定しないことで検証する。

**Acceptance Scenarios**:

1. **Given** 契約更新関連の契約書・社内マニュアル, **When** 担当者が更新チェックリストを生成する, **Then** `artifact_type=renewal_checklist` の draft として確認項目・期限・引用を返す。
2. **Given** 退去・原状回復資料, **When** 担当者が move-out checklist を生成する, **Then** 立会い、鍵返却、精算、負担範囲の確認項目を draft として返す。
3. **Given** 原状回復費用負担の根拠が不足, **When** restoration explanation draft を生成する, **Then** 費用負担を断定せず、担当者または専門家 review が必要であることを表示する。

---

### User Story RE-6 - 管理ダッシュボード (Priority: P3)

管理者が未回答、低評価、頻出質問、よく参照される文書、古い文書候補、問い合わせ傾向、high-risk query 数、risk gate block 数、PoC KPI を確認できる。

**Why this priority**: ナレッジ整備と PoC 効果測定に必要。P1/P2 の業務ログ・feedback・audit が蓄積された後に価値が出る。

**Independent Test**: 一定期間の質問・回答・feedback・draft・risk gate 監査ログから KPI が集計され、権限のある管理者だけが閲覧できることで検証できる。

**Acceptance Scenarios**:

1. **Given** 利用ログと feedback が蓄積されている, **When** 管理者が dashboard を開く, **Then** 未回答、低評価、頻出質問、よく参照される文書、古い文書候補、問い合わせ傾向を確認できる。
2. **Given** high-risk query と risk gate の監査ログ, **When** 管理者が KPI を確認する, **Then** high_risk_query_count と risk_gate_block_count を期間・支店・部署・物件単位で確認できる。
3. **Given** 個人情報を含む問い合わせ履歴, **When** dashboard を表示する, **Then** 必要最小限の個人情報のみ表示し、権限のない個人情報・物件 KPI は表示しない。

---

### Edge Cases

- 契約条件・費用負担・原状回復など high-risk query に対して approved かつ有効な文書引用が無い場合、断定回答しない。
- 根拠が obsolete / draft 文書のみの場合、正式根拠として扱わない。
- 過去対応履歴のみが見つかる場合、「過去事例」「参考」「候補」として表示し、現行契約条件や正式回答として断定しない。
- 入居者名、電話番号、保証人、口座情報など personal data を含む文書は、権限外ユーザーの検索結果・回答・引用・dashboard に出さない。
- 同一物件に複数の Building / Unit / LeaseContract が存在し、部屋番号だけでは一意に決まらない場合は、追加確認または候補提示を行い、推測で契約条件を断定しない。
- 契約期間外、更新日未到来、退去済み、契約解除済みの文書は有効性を明示し、現行条件として断定しない。
- 見積書と請求書の金額が異なる場合、差異を明示し、費用負担判断や請求確定は自動で行わない。
- Excel 台帳のセル引用では、sheet / row / column またはセル範囲を根拠として保持する。
- スキャン PDF / 画像の OCR 信頼度が低い場合、根拠としての信頼度を下げるか、根拠不足として扱う。
- 削除または tombstone 済みの文書・draft・personal data は、検索・回答・citation・cache・dashboard から即時除外される。
- cost budget 超過時は、根拠不足判定や ACL を弱めず `budget_exceeded` または `temporarily_unavailable` とする。

## Requirements *(mandatory)*

> 記法: 本 spec 固有要件は **FR-RE-###**。基盤再利用は `[base:001]`、framework 再利用は `[framework:010]` と明記し、001 の tenant isolation、ACL、citation、groundedness、evaluation、cost、visual RAG、parser abstraction、no-train、audit log 方針および 010 の共通抽象を再定義しない。

### Functional Requirements — Base Reuse / Scope

- **FR-RE-001**: システムは `001-rag-platform` を基盤として利用し、tenant isolation、ACL、citation、groundedness、evaluation、cost、visual RAG、parser abstraction、audit log、no-train provider governance を再定義してはならない。
- **FR-RE-001a**: システムは `010-industry-solution-framework` を利用し、IndustryProfile、MetadataSchema、RiskPolicy、RequiredEvidencePolicy、DraftArtifact、KPI、Dashboard、ACLMapping、GovernanceProfile を再利用しなければならない。`[framework:010]`
- **FR-RE-002**: 本 feature は不動産管理会社・賃貸管理部門・PM 業務向け solution layer に限定し、不動産業界全般、売買仲介、価格査定、入居審査、会計・送金、電子契約を MVP 範囲に含めてはならない。
- **FR-RE-003**: 003 は `002-manufacturing-field-knowledge-rag` を変更してはならず、002 の製造業メタデータ・safety gate・KPI を再利用前提にしてはならない。

### Functional Requirements — Document Ingestion / Metadata

- **FR-RE-010**: システムは PDF / DOCX / XLSX / CSV / 画像 / スキャン PDF を取り込めなければならない。PDF・画像・スキャン PDF・OCR・layout・visual citation は 001 visual RAG を再利用し、DOCX / XLSX / CSV は 001 Parser abstraction を拡張または基盤 parser 実装として扱う。
- **FR-RE-011**: システムは、物件資料、賃貸借契約書、重要事項説明書、管理規約、修繕履歴、点検報告、問い合わせ履歴、オーナー報告書、見積書、請求書、原状回復資料、社内マニュアル、FAQ、会議議事録を扱えなければならない。
- **FR-RE-012**: システムは RealEstateDocumentMetadata を Document / Chunk metadata として付与し、検索 metadata filter、risk gate、citation、dashboard 集計で利用できなければならない。
- **FR-RE-013**: RealEstateDocumentMetadata は少なくとも以下を保持しなければならない: `property_id`, `building_id`, `unit_id`, `room_number`, `owner_id`, `occupant_id`, `lease_contract_id`, `management_contract_id`, `document_type`, `contract_start_date`, `contract_end_date`, `renewal_date`, `move_out_date`, `repair_category`, `incident_type`, `equipment_type`, `vendor_id`, `approval_status`, `approval_source`, `approved_by`, `approved_at`, `effective_date`, `obsolete_at`, `superseded_by`, `legal_risk_category`, `contract_risk_category`, `financial_risk_category`, `personal_data_category`, `owner_department`, `branch_id`, `access_scope`, `no_train_policy_ref`, `retention_policy_ref`.
- **FR-RE-014**: `document_type` は少なくとも `lease_contract`, `important_explanation`, `property_brochure`, `management_rule`, `repair_history`, `inspection_report`, `tenant_inquiry`, `owner_report`, `estimate`, `invoice`, `move_out_document`, `restoration_document`, `internal_manual`, `faq`, `meeting_minutes` を識別できなければならない。`tenant_inquiry` は取り込み元名称として許容するが、入居者エンティティは Occupant / Lessee として表現する。
- **FR-RE-015**: XLSX / CSV 台帳は sheet / row / column / cell_range を citation に利用できる形で保持しなければならない。

### Functional Requirements — Grounded Answer / Risk Gate

- **FR-RE-020**: システムは自然言語質問に対し、001 の retrieval / answer / groundedness / citation を再利用し、物件・部屋・契約・修繕・問い合わせ文脈に沿った根拠付き回答を返せなければならない。
- **FR-RE-021**: 根拠が不足する場合、システムは推測回答をせず `insufficient_evidence` を返さなければならない。
- **FR-RE-022**: システムは high-risk query を判定しなければならない。以下に関わる質問は high-risk とする: 契約条件の断定、費用負担、退去精算、原状回復、更新料・違約金、敷金・保証金、重要事項説明、法的判断、訴訟・クレーム対応、入居審査、個人情報の開示、オーナーと入居者の利害対立、顧客への正式回答、金額請求、契約解除、用途制限、ペット・騒音・近隣トラブル。
- **FR-RE-023**: high-risk query では、`approval_status=approved` かつ `effective_date` が有効な文書引用が無い限り、契約条件・法的判断・費用負担・顧客への正式回答を断定してはならない。
- **FR-RE-024**: draft / obsolete 文書は正式根拠として断定回答に使ってはならない。obsolete 文書に触れる場合は obsolete warning を表示できなければならない。
- **FR-RE-025**: 過去対応履歴、RepairCase、InquiryCase、OwnerReport は「過去事例」「参考」「候補」として表示し、現行契約条件・正式回答・費用負担判断として断定してはならない。
- **FR-RE-026**: 法的判断・契約判断・費用負担判断・顧客への正式回答については、担当者、法務・コンプライアンス担当、または専門家 review が必要であることを表示できなければならない。
- **FR-RE-027**: RiskGateService は RealEstateRiskDecision と RealEstateGateDecision を生成し、high-risk 判定理由、approved citation の有無、有効性、block reason、review required 表示を audit log に記録しなければならない。

### Functional Requirements — Repair / Inquiry / Workflow Support

- **FR-RE-030**: システムは物件・建物・部屋・設備・症状・修繕カテゴリから RepairCase / MaintenanceRequest / InspectionReport / Estimate / Invoice / InquiryCase を検索し、類似事例と対応状況を引用付きで一覧化できなければならない。
- **FR-RE-031**: 修繕履歴や見積・請求に基づく回答では、金額・日付・業者・対応状態・根拠文書を追跡可能にしなければならない。
- **FR-RE-032**: 入居者問い合わせ対応では、契約書・管理規約・過去対応履歴を根拠に occupant_reply draft を生成できなければならない。
- **FR-RE-033**: オーナー報告・修繕報告では、修繕履歴、見積、請求書、点検結果を根拠に owner_report / repair_report draft を生成できなければならない。
- **FR-RE-034**: 契約更新、退去、原状回復、鍵返却、立会い、精算に関する checklist draft を生成できなければならない。

### Functional Requirements — DraftArtifact / Review

- **FR-RE-040**: AI が作成する返信、報告書、修繕報告、オーナー報告、FAQ、チェックリスト、説明文、内部メモは必ず RealEstateDraftArtifact として作成し、`status=draft` を初期状態としなければならない。
- **FR-RE-041**: RealEstateDraftArtifact の `artifact_type` は少なくとも `occupant_reply`, `owner_report`, `repair_report`, `move_out_checklist`, `restoration_explanation`, `renewal_checklist`, `contract_condition_summary`, `faq`, `internal_note` を含まなければならない。
- **FR-RE-042**: RealEstateDraftArtifact は `artifact_id`, `artifact_type`, `status`, `created_by`, `reviewer_id` または `reviewer_group`, `assigned_at`, `reviewed_at`, `review_comment`, `approval_decision`, `source_citations`, `source_document_ids`, `generated_at`, `template_id`, `audit_log_ref` を保持しなければならない。
- **FR-RE-043**: DraftArtifact の状態は `draft | in_review | approved | rejected | archived` とし、AI が自動的に `approved` へ遷移させてはならない。
- **FR-RE-044**: RealEstateDraftReview は reviewer の明示判断、review comment、approval_decision、reviewed_at、audit_log_ref を保持しなければならない。
- **FR-RE-045**: DraftArtifact の生成・review assignment・status transition は audit log 対象でなければならない。

### Functional Requirements — Dashboard / KPI

- **FR-RE-050**: 管理者は未回答質問、低評価回答、頻出質問、よく参照される文書、古い文書候補、問い合わせ傾向、knowledge gap topics、high-risk query 数、risk gate block 数を dashboard で確認できなければならない。
- **FR-RE-051**: RealEstateKPI は少なくとも `self_resolution_rate`, `average_time_to_answer`, `inquiry_response_time_reduction`, `grounded_answer_rate`, `insufficient_evidence_rate`, `low_rating_rate`, `unanswered_question_count`, `frequently_referenced_documents`, `obsolete_document_candidates`, `knowledge_gap_topics`, `draft_review_completion_rate`, `high_risk_query_count`, `risk_gate_block_count`, `repair_case_lookup_count`, `owner_report_draft_count`, `occupant_reply_draft_count` を含まなければならない。
- **FR-RE-052**: dashboard / KPI は tenant、collection、branch、department、property、building、time range で集計できるようにし、権限のない物件・部屋・契約・個人情報・DraftArtifact・KPI を表示してはならない。
- **FR-RE-053**: KPI calculation / export は audit log 対象でなければならない。

### Functional Requirements — ACL / Access Control

- **FR-RE-060**: 003 は 001 ACL を利用し、不動産向け属性を ACL / metadata filter へマッピングしなければならない。新しい認可機構を作ってはならない。
- **FR-RE-061**: ACL / metadata filter へのマッピング対象は少なくとも `branch_id`, `department_id`, `role`, `property_id`, `building_id`, `unit_id`, `owner_id`, `management_scope`, `document_type`, `approval_status`, `personal_data_category` を含まなければならない。
- **FR-RE-062**: 権限のない物件、部屋、契約、入居者情報、問い合わせ履歴、DraftArtifact、dashboard KPI は retrieval result、answer context、citation、admin API response に含めてはならない。
- **FR-RE-063**: 権限外アクセス、ACL denied、tenant isolation denied は audit log 対象でなければならない。

### Functional Requirements — Personal Data / PII

- **FR-RE-070**: 入居者名、住所、電話番号、メール、勤務先、保証人、緊急連絡先、本人確認書類、口座情報、支払い履歴などは personal data として分類しなければならない。
- **FR-RE-071**: personal data は `tenant_id`、ACL、audit、redaction policy、retention policy、no-train policy の対象にしなければならない。
- **FR-RE-072**: ログ、トレース、評価データ、エラー出力、prompt 保存には個人情報を不用意に保存してはならない。必要な場合は redaction / masking / 参照 ID によって扱わなければならない。
- **FR-RE-073**: 管理ダッシュボードでは必要最小限の個人情報のみ表示し、集計で足りる場面では個人情報を表示してはならない。
- **FR-RE-074**: no-train policy は personal data にも適用しなければならない。

### Functional Requirements — No-Train / Governance

- **FR-RE-080**: 顧客がアップロードした文書、契約書、問い合わせ履歴、回答、引用、DraftArtifact、評価データ、ログは、デフォルトではモデル学習・モデル改善に利用してはならない。
- **FR-RE-081**: opt-in なしに、顧客データを横断的なモデル改善や別テナント向け改善に利用してはならない。
- **FR-RE-082**: provider no-train capability は 001-rag-platform 側の provider configuration / contract mode に依存する。003 は provider no-train capability を再定義してはならない。
- **FR-RE-083**: 003 は tenant policy、opt-in / opt-out、audit、governance status、営業・PoC 説明上の no-train 表示を扱わなければならない。
- **FR-RE-084**: 必要な 001 側変更は Base Change Request として記録し、003 内で 001 基盤機能を再定義してはならない。
- **FR-RE-085**: governance status は no-train、audit coverage、risk gate、draft review、groundedness、provider governance status、ISMAP readiness memo、PoC readiness を説明できなければならない。

### Functional Requirements — Audit Log Coverage

- **FR-RE-090**: 少なくとも以下のイベントを audit log 対象にしなければならない: document upload / ingest / parse、RealEstateDocumentMetadata の作成・更新・削除、approval_status の変更、external approval metadata の import、search query、answer generation、citation access、high-risk query 判定、RiskGateService の判断、insufficient evidence response、DraftArtifact の生成、DraftArtifact の review assignment、DraftArtifact の status transition、feedback / low rating、dashboard access、KPI calculation / export、ACL denied、tenant isolation denied、no-train / retention / provider setting changes、deletion / tombstone / cache invalidation。
- **FR-RE-091**: audit log は personal data や契約本文を不用意に保存せず、document_id、chunk_id、citation_id、artifact_id などの参照 ID で追跡しなければならない。
- **FR-RE-092**: audit log は tenant scoped であり、tenant をまたいだ参照を禁止しなければならない。

### Functional Requirements — API Candidates for Planning

- **FR-RE-100**: 後続 plan は少なくとも以下の API 候補を扱えるようにしなければならない: `POST /real-estate/metadata/import`, `POST /real-estate/documents/enrich`, `GET /real-estate/properties/{property_id}/knowledge`, `GET /real-estate/units/{unit_id}/knowledge`, `POST /real-estate/workflows/contract-question`, `POST /real-estate/workflows/repair-investigation`, `POST /real-estate/workflows/occupant-reply-draft`, `POST /real-estate/workflows/owner-report-draft`, `POST /real-estate/workflows/move-out-checklist-draft`, `POST /real-estate/workflows/restoration-explanation-draft`, `GET /real-estate/drafts/{artifact_id}`, `POST /real-estate/drafts/{artifact_id}/review`, `GET /real-estate/dashboard`, `GET /real-estate/kpi`, `GET /real-estate/audit`, `GET /real-estate/governance/status`。
- **FR-RE-101**: 上記 API 候補は 001 の authentication、tenant isolation、ACL、citation、audit、cost、groundedness の基盤制約に従わなければならない。

## Key Entities *(include if feature involves data)*

### Property
管理対象物件。`property_id`, `tenant_id`, `name`, `address`, `branch_id`, `management_scope`, `owner_id?` を持つ。Building / Unit / LeaseContract / RepairCase / InquiryCase の上位スコープ。

### Building
物件内の建物。`building_id`, `tenant_id`, `property_id`, `name`, `address`, `structure`, `built_at`, `management_scope` を持つ。

### Unit
部屋・区画。`unit_id`, `tenant_id`, `property_id`, `building_id`, `room_number`, `floor`, `layout`, `occupancy_status`, `current_lease_contract_id?` を持つ。

### Owner
物件オーナー。`owner_id`, `tenant_id`, `name`, `contact_ref`, `owner_department?`, `personal_data_category`, `access_scope` を持つ。個人オーナーの場合は personal data として扱う。

### Occupant / Lessee
入居者・借主。`occupant_id`, `tenant_id`, `unit_id`, `lease_contract_id?`, `name`, `contact_ref`, `emergency_contact_ref?`, `guarantor_ref?`, `personal_data_category` を持つ。platform tenant と混同しない。

### LeaseContract
賃貸借契約。`lease_contract_id`, `tenant_id`, `property_id`, `building_id`, `unit_id`, `occupant_id`, `owner_id`, `contract_start_date`, `contract_end_date`, `renewal_date`, `deposit`, `key_money?`, `renewal_fee?`, `penalty_terms?`, `document_id?`, `approval_status` を持つ。

### LeaseTerm
契約条件の正規化レコード。`lease_term_id`, `tenant_id`, `lease_contract_id`, `term_type`, `term_value`, `effective_date`, `source_citation_id`, `approval_status_at_use` を持つ。

### PropertyManagementAgreement
管理委託契約。`management_contract_id`, `tenant_id`, `property_id`, `owner_id`, `management_scope`, `contract_start_date`, `contract_end_date`, `fee_terms`, `document_id?` を持つ。

### RepairCase
修繕ケース。`repair_case_id`, `tenant_id`, `property_id`, `building_id?`, `unit_id?`, `equipment_type`, `repair_category`, `incident_type`, `status`, `occurred_at`, `completed_at?`, `vendor_id?`, `estimate_id?`, `invoice_id?`, `source_document_ids` を持つ。

### MaintenanceRequest
入居者・オーナー・社内からの修繕依頼。`maintenance_request_id`, `tenant_id`, `property_id`, `unit_id?`, `occupant_id?`, `owner_id?`, `received_at`, `channel`, `symptom`, `status`, `repair_case_id?` を持つ。

### InspectionReport
点検報告。`inspection_report_id`, `tenant_id`, `property_id`, `building_id?`, `unit_id?`, `equipment_type`, `inspected_at`, `findings`, `source_document_id`, `vendor_id?` を持つ。

### Vendor
修繕業者・点検業者。`vendor_id`, `tenant_id`, `name`, `trade_type`, `contact_ref`, `access_scope` を持つ。

### Estimate
見積書。`estimate_id`, `tenant_id`, `repair_case_id?`, `vendor_id`, `amount`, `currency`, `issued_at`, `valid_until?`, `source_document_id`, `approval_status` を持つ。

### Invoice
請求書。`invoice_id`, `tenant_id`, `repair_case_id?`, `vendor_id?`, `owner_id?`, `occupant_id?`, `amount`, `issued_at`, `due_date?`, `source_document_id`, `payment_status?` を持つ。会計・送金処理そのものは非ゴール。

### MoveOutCase
退去ケース。`move_out_case_id`, `tenant_id`, `property_id`, `unit_id`, `occupant_id`, `lease_contract_id`, `move_out_date`, `handover_date?`, `status`, `source_document_ids` を持つ。

### RestorationCase
原状回復ケース。`restoration_case_id`, `tenant_id`, `move_out_case_id`, `repair_case_id?`, `restoration_items`, `estimated_amount?`, `charged_amount?`, `burden_policy_ref?`, `source_citations` を持つ。費用負担判断は high-risk。

### InquiryCase
入居者・オーナー・社内問い合わせ。`inquiry_case_id`, `tenant_id`, `property_id?`, `unit_id?`, `occupant_id?`, `owner_id?`, `channel`, `received_at`, `topic`, `status`, `source_document_ids`, `reply_artifact_id?` を持つ。

### OwnerReport
オーナー報告。`owner_report_id`, `tenant_id`, `owner_id`, `property_id`, `period`, `source_document_ids`, `draft_artifact_id?`, `approved_artifact_id?` を持つ。

### RealEstateDocumentMetadata
不動産文書メタデータ。FR-RE-013 の全項目を保持し、Document / Chunk metadata に格納される。

### RealEstateDraftArtifact
AI 生成物。FR-RE-041/042 の artifact type と fields を持つ。AI 生成時は必ず `status=draft`。

### RealEstateDraftReview
DraftArtifact のレビュー記録。`review_id`, `tenant_id`, `artifact_id`, `reviewer_id?`, `reviewer_group?`, `assigned_at`, `reviewed_at`, `review_comment`, `approval_decision`, `audit_log_ref` を持つ。

### RealEstateRiskDecision
High-risk 判定結果。`risk_decision_id`, `tenant_id`, `query_id?`, `is_high_risk`, `risk_categories`, `reason_codes`, `classification_source`, `created_at`, `audit_log_ref` を持つ。

### RealEstateGateDecision
Risk gate の判断結果。`gate_decision_id`, `tenant_id`, `risk_decision_id`, `blocked`, `block_reason`, `approved_effective_citation_present`, `review_required`, `obsolete_warning`, `draft_warning`, `source_citation_ids`, `audit_log_ref` を持つ。

### RealEstateKPI
FR-RE-051 の KPI 指標、集計軸（tenant / collection / branch / department / property / time_range）、`calculated_at`, `source_audit_log_range`, `export_ref?` を持つ。

## Relationships

- Property 1—N Building / Unit / LeaseContract / RepairCase / InquiryCase / OwnerReport
- Building 1—N Unit / InspectionReport / RepairCase
- Unit 1—N LeaseContract / MaintenanceRequest / MoveOutCase / RestorationCase
- Owner 1—N PropertyManagementAgreement / OwnerReport / Property
- Occupant(Lessee) 1—N LeaseContract / InquiryCase / MaintenanceRequest / MoveOutCase
- RepairCase 1—N Estimate / Invoice / InspectionReport references
- InquiryCase 0—1 RealEstateDraftArtifact reply draft
- RealEstateDraftArtifact N—M Citation via `source_citations`
- RealEstateDocumentMetadata annotates 001 Document / Chunk metadata
- RealEstateRiskDecision 1—1 RealEstateGateDecision for gated answer/draft workflows
- RealEstateKPI derives from audit log / feedback / evaluation / draft review state

## Success Criteria *(mandatory)*

- **SC-RE-001**: 契約条件・費用負担・原状回復など high-risk query では、approved かつ有効な文書引用がない限り断定回答しない。
- **SC-RE-002**: AI 生成物は自動的に approved にならず、初期状態は 100% `draft` である。
- **SC-RE-003**: 権限のない物件・契約・個人情報が検索結果、回答、引用、ダッシュボードに 0 件も出ない。
- **SC-RE-004**: 根拠不足の場合は `insufficient_evidence` を返し、推測回答を返さない。
- **SC-RE-005**: obsolete / draft 文書を正式根拠として断定回答に使わない。
- **SC-RE-006**: no-train policy が標準で有効であり、opt-in なしのモデル学習・横断改善・別テナント向け改善利用が 0 件である。
- **SC-RE-007**: dashboard で未回答、低評価、頻出質問、古い文書候補、high-risk query 数、risk gate block 数を確認できる。
- **SC-RE-008**: PoC KPI（self_resolution_rate、average_time_to_answer、inquiry_response_time_reduction、grounded_answer_rate、draft_review_completion_rate など）を計測できる。
- **SC-RE-009**: personal data はログ、トレース、評価データ、エラー出力に不用意に保存されない。
- **SC-RE-010**: 001 の tenant isolation / ACL / citation / groundedness / evaluation / cost / visual RAG / parser abstraction / audit / no-train provider governance を再定義していないことを spec review で確認できる。
- **SC-RE-011**: 002 のファイルや要件を変更していないことを spec review で確認できる。

## Non-Goals *(mandatory)*

- 法的判断の自動確定
- 宅建業法、借地借家法、消費者契約法などの法令解釈の最終判断
- 契約レビューの自動確定
- 重要事項説明の自動実施
- 賃料査定・不動産価格査定・売買価格査定の自動確定
- 入居審査の自動判断
- 与信判断・信用スコアリング
- 電子契約・電子署名
- 基幹の不動産管理システムそのもの、またはその置き換え
- 会計・入出金・送金処理
- 設備制御や IoT 連携
- 音声 RAG
- 動画 RAG
- フル DMS / 任意版 rollback
- 002 manufacturing solution layer の変更または再利用前提化

## Dependencies & Assumptions

- 001 の tenant isolation、ACL pre-filter、tombstone、citation、groundedness、evaluation、cost、visual RAG、parser abstraction、audit log、provider governance が利用可能である。
- DOCX / XLSX / CSV parser は 001 Parser abstraction の実装として提供される。003 は parser abstraction 自体を変更しない。
- 不動産入居者は platform tenant と混同しないため、仕様・API・データモデルでは Occupant / Lessee を使う。
- 003 固有の no-train / governance 表示は tenant policy と audit 上の product layer 要件として扱い、provider no-train capability の検証は 001 側 Base Change Request に依存する。
- Base Change Request が必要な場合は、001 をこの spec 内で再定義せず、後続 plan で明示的に記録する。

## NEEDS CLARIFICATION

現時点では無し。
