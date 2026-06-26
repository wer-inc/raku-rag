# Feature Specification: Manufacturing Field Knowledge RAG (Solution Layer)

**Feature Branch**: `002-manufacturing-field-knowledge-rag`

**Created**: 2026-06-18

**Status**: Draft

**Input**: 製造業向け「現場ナレッジRAG」solution layer。設備保全・品質保証・作業手順確認・技術継承・新人教育を支援する根拠付きAIアシスタント。`001-rag-platform` を基盤、`010-industry-solution-framework` を業界 solution framework として利用する。

## Relationship to Base Platform (001-rag-platform)

本 spec は **solution layer** であり、汎用RAG基盤 `001-rag-platform` の上に構築する。以下の基盤機能は
**再定義せず再利用**する（参照のみ。詳細は `specs/001-rag-platform/spec.md`）：

- マルチテナント分離・ACL（deny-by-default, pre-filter）・認証（署名付きトークン）— 001 FR-021〜025a
- citation / used_chunks / traceability — 001 FR-012〜015
- groundedness（2段階ゲート、根拠不足は推測しない）— 001 FR-014
- ingestion / chunk / embedding / 検索 / 回答 / 削除（tombstone）— 001 FR-001〜011
- evaluation gate・cost budget・observability — 001 FR-017/026〜028/032〜034
- visual RAG（OCR/layout/visual citation, captioning optional）— 001 US6 / FR-035〜052

本 spec が新たに定義するのは **製造業ドメイン固有**の：追加ドキュメント形式、データモデル（製造業
エンティティ）、ユースケース、UI/ワークフロー、ドラフト生成、安全/承認ポリシー、現場KPI のみ。

## Relationship to Industry Solution Framework (010-industry-solution-framework)

本 spec は `010-industry-solution-framework` の **Manufacturing IndustryProfile** としても解釈できる。010 の共通抽象を再定義せず、以下のようにマッピングする。

- ManufacturingDocumentMetadata → 010 `MetadataSchema` / `MetadataFieldDefinition`
- 製造業 document_type → 010 `DocumentTypeDefinition`
- Factory / ProductionLine / Process / Equipment / Product / Part / TroubleCase 等 → 010 `EntityTypeDefinition`
- safety / quality / equipment operation high-risk 判定 → 010 `RiskPolicy` / `RequiredEvidencePolicy`
- approved / effective document citation requirement → 010 `ApprovalPolicy` / `RequiredEvidencePolicy`
- checklist / trouble_report / quality_report / training_material / faq → 010 `DraftArtifactTypeDefinition`
- DraftArtifact review → 010 `DraftReviewPolicy`
- PoC KPI / dashboard → 010 `KPIDefinition` / `DashboardWidgetDefinition`
- factory_id / line_id / process_id / equipment_id / owner_department / access_scope → 010 `ACLMappingPolicy`

010 は共通 contract と profile registry を提供するだけであり、製造業固有の safety semantics は本 002 spec に残す。**（analyze I3 — 依存境界の明確化）**: この 010 へのマッピングは **概念対応（Manufacturing IndustryProfile としても解釈できる）であり、ビルド時依存ではない**。002 の唯一のビルド依存は 001 であり、010 をビルド/実行時の必須依存にしない（plan.md「Analyze 整合メモ」と同旨）。

### Architecture Overview（001 + 010 + 002 + governance overlay） [CR:G6]

1. **001-rag-platform = Base RAG Platform**: tenant 分離・ACL・ingestion・retrieval・answer・citation・
   groundedness・evaluation・cost・audit・visual RAG などの基盤を提供。
2. **010-industry-solution-framework = Industry Solution Framework**: IndustryProfile、MetadataSchema、RiskPolicy、RequiredEvidencePolicy、DraftArtifact、KPI、Dashboard、ACLMapping、GovernanceProfile などの共通 contract を提供。
3. **002-manufacturing-field-knowledge-rag = Manufacturing Solution Layer**: 製造業メタデータ・設備保全・
   品質不良・類似トラブル・DraftArtifact・承認状態・high-risk safety gate・PoC KPI・dashboard を提供。
4. **Product / Governance Overlay = Cross-cutting governance overlay**: no-train policy・audit coverage・
   AIガバナンス説明・ISMAP readiness memo・PoC readiness・provider governance status を扱う**横断レイヤー**。

> 重要: Product/Governance Overlay は **独立した第3 feature branch ではなく**、本 002 spec 内の
> product readiness / governance 要件（FR-MFG-016〜030, Hard Rules 7〜9）と Base CR-001-A〜D への依存と
> して実現する。001 を再定義する新しいRAG基盤ではない（001 基盤 ＋ 002 solution layer ＋ 横断 overlay）。

## Clarifications

### Session 2026-06-18

- Q1（承認ライフサイクルの責務）→ **A: 軽量承認ワークフロー + 外部承認情報の取り込み（Custom-C）**。本 layer は `approval_status`・`effective_date`・`approved_by`・`approved_at`・`obsolete_at`・`superseded_by`・`approval_source` を保持。ライフサイクルは `draft → pending_review → approved → obsolete`。取り込み元（QMS/DMS/SharePoint/Box/PLM 等）が承認状態を持つ場合は **imported approval** として取り込み source of truth として扱える。外部承認があればそれを消費、無ければ本 layer の軽量ワークフローで補完。フルDMS/QMS/PLM・本文編集・差分表示・任意版rollback・複雑承認経路・電子署名・法定文書管理は MVP 対象外。
- Q2（ドラフトのレビュー導線）→ **A: 本 layer がレビュー導線を持つ（B）**。DraftArtifact は `status`（`draft → in_review → approved/rejected/archived`）と `reviewer_id`・`reviewer_role`・`assigned_at`・`reviewed_at`・`review_comment`・`approval_decision` を保持。AI生成物は必ず `draft` で作成され自動 approved にならない。単一 reviewer または reviewer group による軽量レビュー（多段承認・電子署名は対象外）。レビュー済みでも根拠文書・引用・生成時刻・生成者・使用テンプレート・使用文書一覧を audit trail で追跡。
- Q3（safety gating の判定）→ **A: 文書/メタデータ分類タグ ＋ クエリ意図分類の組み合わせ（C）**。文書側 metadata（`document_type`・`approval_status`・`safety_category`・`quality_category`・`equipment_operation_category`・`hazard_tags`・`process_id`・`equipment_id`）とクエリ意図（設備停止/分解/感電/高温/高圧/薬品/重量物/安全装置/品質判定/出荷可否/顧客影響/是正処置 等）を併用。**どちらか一方でも該当すれば high-risk query** として安全側に倒す。判定は metadata＋ルール＋キーワード＋LLM分類を組み合わせ、迷う場合は high-risk として扱う。

### Session 2026-06-18 — Product Readiness / Governance CR

製品販売・PoC・大企業導入に向けた追加（既存 Hard Rules/FR-MFG/SC-MFG/Entities と矛盾しない範囲）：

- **No-Train（既定）**: 顧客データは opt-in 無しに学習・改善へ使用しない。外部 provider も no-train mode 前提（FR-MFG-016〜020, Hard Rule 7, SC-MFG-009）。
- **Audit Log 網羅・構造化**: 規定イベントを tenant-scoped・tamper-evident に記録、PII/機密本文は参照IDで追跡（FR-MFG-021〜023, Hard Rule 8, SC-MFG-010）。
- **Governance/ISMAP Readiness**: AI事業者ガイドライン/ISMAP は「見据えた設計」の design memo/NFR として記録（取得・完全準拠は MVP 非ゴール）（FR-MFG-024〜026, Hard Rule 9）。
- **PoC v0**: vertical slice と PoC KPI を定義（FR-MFG-027/028, SC-MFG-012）。
- **Base CRs**: 横断要件は 001 を再定義せず Base CR-001-A〜D として明記。
- GQ1 no-train フォールバック / GQ2 retention 既定値は末尾「Open Questions (Governance CR)」で解決済み。GQ1=block、GQ2=顧客データ 365 日 / 監査ログ 365 日を既定とする。

### Session 2026-06-18 — Coverage Alignment (G1–G6, ナラティブ↔spec ズレ解消)

製品ナラティブと spec のズレ6件を反映（新規大スコープは追加せず、明記のみ）：

- **G1 FAQ**: DraftArtifact に `faq` 追加（FR-MFG-010, US4-3, Entity）。draft 扱い・自動approved禁止を維持。
- **G2/G3 Safety Telemetry**: ダッシュボードに `high_risk_query_count`・`safety_gate_block_count`（内訳付き）を追加（FR-MFG-012/030, US5-2, FR-MFG-028, SC-MFG-013）。既存の判定・監査の集計で実現。
- **G4 暫定/恒久**: Countermeasure に `measure_class`(provisional/permanent/unknown) を追加、`type` と役割分離（FR-MFG-008/009, US3, Entity）。
- **G5 no-train 責務境界**: 002=policy/opt-in/governance表示、001=provider設定検証（FR-MFG-029, Base CR-001-B 改題）。
- **G6 レイヤリング**: Architecture Overview を追加（001基盤＋010 industry framework＋002 solution layer＋横断 Governance Overlay。010 は共通 contract であり、001 を再定義しない）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 現場担当者が根拠付きで即答を得る (Priority: P1)

現場担当者が設備アラームや不良に直面したとき、自然言語で質問し、設備マニュアル・作業標準書・過去
トラブル報告に基づく**根拠付き回答**（出典・該当箇所つき）を得る。根拠が不足する場合は推測せず
「根拠不足」と返る。安全・品質・設備操作に関わる回答は**承認済み文書の引用を必須**とする。

**Why this priority**: ソリューションの中核価値（自己解決・現場即応）。基盤の検索/回答/引用/根拠不足に
製造業メタデータと安全ポリシーを重ねた最小成立単位。

**Independent Test**: 設備マニュアル＋過去トラブルを取り込み、(a) アラームコードに対する質問→承認済み
文書を引用した回答、(b) 安全文書の根拠が無い危険作業の質問→断定せず根拠不足/注意喚起、で検証。

**Acceptance Scenarios**:

1. **Given** 承認済み設備マニュアルと過去トラブルが取り込み済み, **When** 現場担当者が「アラーム E-152 の対処は？」と聞く, **Then** 該当手順を、document/citation・effective_date・approval_status つきで返す。
2. **Given** 安全文書（承認済み）が存在しない危険作業の質問, **When** ユーザーが質問する, **Then** 断定せず、安全根拠が無い旨を明示し推測回答しない。
3. **Given** 回答根拠が obsolete 文書にしか無い, **When** ユーザーが質問する, **Then** policy に従い obsolete を一次根拠にせず、注意表示または根拠不足とする。

---

### User Story 2 - 製造業ドキュメントの取り込みとメタデータ付与 (Priority: P1)

管理者が DOCX/XLSX/CSV/PDF/画像/図表/スキャンPDF を取り込み、設備名・型番・アラームコード・不良種別・
工程名・部品番号・顧客名などの**製造業メタデータ**と、`approval_status`（latest_approved/draft/
obsolete）・`effective_date` を付与する。

**Why this priority**: US1 の根拠データがこの経路で入る。メタデータと承認状態が無いと安全/承認ポリシーが
成立しない。

**Independent Test**: 各形式のサンプルを取り込み→正規化・チャンク・index 化を確認、製造業メタデータと
approval_status/effective_date が検索フィルタ・引用に反映されることを検証。

**Acceptance Scenarios**:

1. **Given** XLSX 台帳・DOCX 標準書・PDF 図面・スキャン点検表, **When** 取り込みジョブを実行, **Then** 各文書が正規化・index 化され、設備/工程/部品等のメタデータが付与される（基盤 ingestion を再利用）。
2. **Given** 取り込み文書, **When** approval_status と effective_date を設定, **Then** 検索・回答で latest_approved / obsolete / 有効日が識別できる。

---

### User Story 3 - 過去トラブルの類似事例・原因・対策の一覧化 (Priority: P2)

現場・保全担当が、現在の症状に類似する過去 TroubleCase を検索し、原因(FailureMode)・対策
(Countermeasure)・再発防止策を一覧で参照する。対策は**正式手順ではなく候補・参考**として表示する。

**Why this priority**: 技術継承・再発防止の中核。US1 の上に成り立つ知識活用。

**Independent Test**: 症状クエリ→類似 TroubleCase 一覧（原因・対策・再発防止・出典つき）が返り、対策が
「参考/候補」ラベルで表示されることを検証。

**Acceptance Scenarios**:

1. **Given** 過去トラブル報告が取り込み済み, **When** 「振動増加＋異音」で検索, **Then** 類似 TroubleCase が原因・対策・再発防止策・引用つきで一覧化され、対策が **暫定（provisional）/恒久（permanent）に分けて**表示される。
2. **Given** 過去対策が見つかる, **When** 対策を表示, **Then** 「参考/候補（正式手順ではない）」と明示され、`measure_class=permanent` でも過去事例由来は断定せず候補表示される。

---

### User Story 4 - ドラフト生成（チェックリスト/報告書/教育資料/FAQ） (Priority: P2)

ユーザーが点検チェックリスト・トラブル報告書・品質報告・教育資料・**FAQ** の**ドラフト**を生成する。
生成物はすべて `draft` として扱い、人間レビューを前提とする。根拠には引用を付す。

**Why this priority**: 業務アプリとしての差別化価値（報告作成負荷の削減）。安全のため必ず draft 扱い。

**Independent Test**: 点検チェックリスト生成→`draft` 状態・引用つき・レビュー前提の表示を確認。承認済み
根拠が無い安全項目は断定しないことを確認。

**Acceptance Scenarios**:

1. **Given** 設備と作業標準書, **When** 点検チェックリストのドラフト生成を依頼, **Then** `status=draft`・引用つきのチェックリスト案が返り、レビュー必須と明示される。
2. **Given** トラブル事例, **When** トラブル報告書ドラフトを生成, **Then** 事実は引用に基づき、未確定事項は draft 上で明示される。
3. **Given** よくある質問の元文書, **When** **FAQ ドラフト**生成を依頼, **Then** `status=draft`・`source_citations`/`source_document_ids` つきの FAQ 案が返り、**自動 approved にならず** reviewer による approve まで draft として扱われ、正式公開物にならないと明示される。

---

### User Story 5 - 管理者によるナレッジ運用ダッシュボード (Priority: P3)

工場長/情報システム管理者が、未回答質問・低評価回答・頻出質問・よく参照される文書・古い(obsolete/
期限切れ)文書・ナレッジ不足領域、および **Safety Telemetry**（high-risk query 数・safety-gate block 数）を
確認する。

**Why this priority**: ナレッジ整備の PDCA に必要だが、回答機能(US1)成立後の運用レイヤー。

**Independent Test**: ダッシュボードで未回答質問・低評価・頻出文書・stale 文書・ナレッジギャップが集計
表示されることを確認。

**Acceptance Scenarios**:

1. **Given** 一定期間の利用ログ, **When** 管理者がダッシュボードを開く, **Then** 未回答質問数・低評価回答・頻出質問・頻出文書・古い文書・ナレッジ不足領域が表示される。
2. **Given** high-risk query と safety gate の監査ログ, **When** 管理者が Safety Telemetry を開く, **Then** `high_risk_query_count` と `safety_gate_block_count`（断定停止/insufficient化/approved citation不足ブロックの内訳）が tenant/collection/factory/department/time range で集計表示される。

---

### User Story 6 - 部署/工場/役職/設備領域ごとのアクセス制御 (Priority: P2)

管理者が、部署・工場・役職・設備領域ごとに文書/ナレッジへのアクセス権限を制御する（基盤 ACL を
製造業スコープにマッピング）。

**Why this priority**: 製造業の機密（顧客名・不良・図面）保護に必須。基盤 ACL の上のマッピング定義。

**Independent Test**: 工場A保全の権限で工場B品質の文書が検索・回答・引用に出ないことを確認（基盤の
tenant/ACL pre-filter を再利用）。

**Acceptance Scenarios**:

1. **Given** 工場・部署・役職・設備領域の権限定義, **When** 権限外ユーザーが質問, **Then** 権限外文書は結果・回答・引用に出ない（001 FR-022 を再利用）。

---

### Edge Cases

- 安全/品質/設備操作の質問で、承認済み文書の根拠が無い → 断定せず根拠不足/注意喚起（safety gating）。
- 危険作業（設備停止・分解・薬品・高温・高圧・感電）→ 安全文書の根拠が無い限り手順を断定しない。
- 回答根拠が obsolete / draft 文書のみ → policy に従い一次根拠にしない、または注意表示。
- Excel 台帳のセル参照で根拠を示す必要がある → 行/列/シートを引用範囲として保持。
- 過去対策が現行設備に不適合の可能性 → 「参考・候補」明示、正式手順としない。
- effective_date が未来 / 失効済み → 有効期間外として扱い、回答での扱いを policy 制御。

## Requirements *(mandatory)*

> 記法: 本 spec 固有要件は **FR-MFG-###**。基盤再利用は [base:FR-0xx] と明記し再定義しない。

### Functional Requirements — ドキュメント形式・取り込み

- **FR-MFG-001**: システムは DOCX・XLSX・CSV を取り込み・正規化できなければならない（基盤 Parser 抽象 [base:FR-031] に新規 parser を追加）。PDF・画像・図表・スキャンPDF は基盤を再利用 [base:FR-002/035]。
- **FR-MFG-002**: XLSX/CSV 台帳は、行/列/シート構造を保持し、セル単位の引用範囲を示せなければならない（基盤 offset/citation [base:FR-013] を表構造へ拡張）。
- **FR-MFG-003**: 取り込み時に **製造業メタデータ** を付与できなければならない：設備名・型番・アラームコード・不良種別・工程名・部品番号・顧客名 等（基盤 Document/Chunk metadata [base] に格納し、検索 metadata filter [base:FR-010] で利用）。

### Functional Requirements — 承認・有効性ポリシー

- **FR-MFG-004**: 文書は承認メタデータ `approval_status`（draft/pending_review/approved/obsolete）・`effective_date`・`approved_by`・`approved_at`・`obsolete_at`・`superseded_by`・`approval_source` を保持・識別できなければならない。本 layer は **軽量承認ワークフロー**（draft→pending_review→approved→obsolete）を提供する。
- **FR-MFG-004a**: 取り込み元システムが承認状態を持つ場合、それを **imported approval** として取り込み source of truth として扱えなければならない。外部承認が無い場合は本 layer の軽量ワークフローで補完する。フルDMS/QMS/PLM・本文編集・差分表示・任意版rollback・複雑承認経路・電子署名・法定文書管理は対象外（非ゴール）。
- **FR-MFG-005**: safety / quality / equipment operation に関する回答（high-risk query, FR-MFG-015）では、**`approved` かつ `effective_date` が有効な文書の引用を必須**としなければならない。承認済み根拠が無い場合は断定してはならない。
- **FR-MFG-006**: draft / obsolete 文書は policy により検索対象にできるが、**正式根拠として断定回答に使ってはならない**。obsolete 文書を参照する場合は **obsolete warning を必須表示**しなければならない。
- **FR-MFG-007**: 危険作業（設備停止・分解・薬品・高温・高圧・感電・重量物等）に関わる内容は、安全文書（approved/有効）の根拠が無い限り手順を断定してはならない。high-risk query では「作業実施前に現場責任者または有資格者の確認が必要」である旨を表示できなければならない（基盤 groundedness [base:FR-014] に safety gating を上乗せ）。
- **FR-MFG-015**: システムは **high-risk query 判定** を、文書/メタデータ分類タグ（`document_type`・`safety_category`・`quality_category`・`equipment_operation_category`・`hazard_tags`・`process_id`・`equipment_id`）と **クエリ意図分類**（設備停止/分解/感電/高温/高圧/薬品/重量物/安全装置/品質判定/出荷可否/顧客影響/是正処置 等）の **組み合わせ** で行わなければならない。どちらか一方でも該当すれば high-risk として安全側に倒す。判定は metadata＋ルール＋キーワード＋LLM分類を併用し、判定に迷う場合は high-risk として扱う。high-risk では FR-MFG-005/006/007/009 を適用する。

### Functional Requirements — 知識活用・ドラフト生成

- **FR-MFG-008**: システムは、症状クエリ（類似トラブル/品質不良検索）に対し類似 TroubleCase と、その FailureMode（原因）・Countermeasure（対策）・再発防止策を引用つきで一覧化できなければならない。対策は **暫定対策（provisional）と恒久対策（permanent）を分けて表示** できなければならない（`Countermeasure.measure_class`）。
- **FR-MFG-009**: 対策には2軸を用いる：`type`（参考/候補などの**表示・evidence区分**）と `measure_class`（**暫定/恒久/分類不明の性質区分**）。過去事例に基づく対策は、`measure_class` が permanent であっても正式手順として断定せず、**「過去事例に基づく候補・参考」** として明示表示しなければならない。
- **FR-MFG-010**: システムは、点検チェックリスト・トラブル報告書・品質報告・教育資料・**FAQ** の **ドラフト** を生成できなければならない。AI生成物はすべて `status=draft` で作成され、**自動的に approved になってはならない**。FAQ ドラフトも他のドラフトと同様に `source_citations`・`source_document_ids`・`template_id`・`review_status`・`audit_log_ref` を持ち、reviewer による approve までは正式公開物ではなく draft として扱う。
- **FR-MFG-010a**: DraftArtifact は状態 `draft → in_review → approved/rejected/archived` を持ち、`reviewer_id`・`reviewer_role`・`assigned_at`・`reviewed_at`・`review_comment`・`approval_decision` を保持しなければならない。管理者または指定 reviewer がレビューしない限り、正式な作業指示・品質判定・顧客提出物・教育資料の確定版として扱ってはならない（単一 reviewer または reviewer group による軽量レビュー。多段承認・電子署名は対象外）。
- **FR-MFG-010b**: レビュー済み DraftArtifact でも、根拠文書・引用・生成時刻・生成者・使用テンプレート・使用文書一覧を **audit trail** で追跡できなければならない。
- **FR-MFG-011**: 生成ドラフトは、事実根拠に引用を付し、未確定/未承認事項を draft 上で明示しなければならない。安全項目は承認済み根拠が無ければ断定しない（FR-MFG-005 準拠）。

### Functional Requirements — 運用・権限・KPI

- **FR-MFG-012**: 管理者は、未回答質問・低評価回答・頻出質問・頻出参照文書・古い(obsolete/期限切れ)文書・ナレッジ不足領域、および **Safety Telemetry**（`high_risk_query_count`・`safety_gate_block_count`、FR-MFG-030）を確認できなければならない（基盤 feedback/observability [base:FR-016/017/027] を集計）。
- **FR-MFG-013**: アクセス権限を 部署 / 工場 / 役職 / 設備領域 ごとに制御できなければならない（基盤 ACL [base:FR-022/025a] へのマッピングとして定義。新たな認可機構は作らない）。マッピング: **部署=base ACL group/role**、**工場=Factory エンティティ**、役職=role、設備領域=Process/Equipment メタデータ。department は新規エンティティを作らず base ACL の group/role として表現する。
- **FR-MFG-014**: システムは PoC KPI を計測できなければならない：自己解決率・回答時間削減・問い合わせ削減・根拠付き回答率・未回答質問数（基盤 evaluation/metrics [base:FR-017/026] を利用。具体指標は FR-MFG-028）。
- **FR-MFG-030 (Safety Telemetry)** [CR:G2/G3]: ダッシュボードは **`high_risk_query_count`** と **`safety_gate_block_count`** を表示できなければならない。
  - **算出の単一の真実源（source of truth）= audit log（FR-MFG-021/022）**。telemetry を別途持つ場合も audit log から導出し、二重カウントしない。
  - **`safety_gate_block_count` の内訳は相互排他**とし、1回のブロックにつき **主因を1つだけ**カウントする（state machine）：(1) `approved_citation_missing`（approved/有効な引用が無く断定を止めた）→ (2) `insufficient_evidence`（pre/post ゲートで根拠不足に倒した）→ (3) `other_block`。判定順は (1)→(2)→(3) の優先順で 1 件に分類（断定停止＝(1)+(3) を含む上位概念ではなく、主因コード1つに正規化）。
  - **集計軸**: tenant / collection / factory / department / time range。`factory`・`department` は **actor の組織コンテキスト**（部署=base ACL group/role、工場=Factory）と resource の製造業メタデータ（`process_id`/`equipment_id` 等）から導出する。集計に必要な `factory_id`/`department_id` は AuditLogEntry の actor 組織コンテキストとして保持する（下記 Entity）。
  - time range の粒度（hourly/daily/custom）は設定可能とし、telemetry の retention は DataUsePolicy の retention に従う。
  - 新たな安全機構は作らず、既存の SafetyGate / HighRiskClassifier 判定（FR-MFG-015）の監査を集計するのみ。

### Functional Requirements — No-Train / Customer Data Use Policy [CR: Governance]

- **FR-MFG-016**: 顧客がアップロードした文書・画像・OCR結果・Excel/Word/PDF内容・メタデータ・質問・回答・引用・DraftArtifact・フィードバック・評価データ・ログは、**デフォルトでモデル学習・モデル改善に使用してはならない（no-train by default）**。
- **FR-MFG-017**: 外部 LLM/VLM/Embedding/OCR provider を利用する場合も、顧客データが provider の学習に使われない設定・契約・APIモード（**no-train mode**）を利用することを前提とする。no-train を保証できる provider のみを既定で利用可能とする（provider の no-train capability は基盤側の Base CR-001-B に依存）。no-train を保証できる provider が無い capability は GQ1 の決定に従い既定で block する。
- **FR-MFG-018**: 顧客データを学習/fine-tuning/評価改善/ベンチマーク作成に使う場合は、**tenant admin による明示的 opt-in と別契約を必須**としなければならない。opt-in 無しに、横断的なモデル改善や別テナント向け改善に利用してはならない。
- **FR-MFG-019**: no-train policy は、営業資料・管理画面・契約説明・監査資料で説明可能な形で提示でき、`policy_version` を持たなければならない。policy 変更は audit log の対象とする（FR-MFG-021）。
- **FR-MFG-020**: 顧客データの **保持期間・削除・export・監査ログとの関係** を明確化し、tenant 単位で設定可能としなければならない。削除は基盤 tombstone/カスケード [base:FR-008] を再利用し、export と retention は Base CR-001-C と連携する。保持期間の既定値は GQ2 の決定に従い顧客データ 365 日 / 監査ログ 365 日とする。
- **FR-MFG-029 (No-train 責務境界)** [CR:G5]: no-train は **002 の product/governance 方針**として保持する。ただし provider の実際の no-train 保証は **001 側の provider capability / provider configuration / contract mode に依存**する。責務境界は次のとおり：
  - **002（本 layer）**: tenant policy（DataUsePolicy）、opt-in / opt-out、no-train の audit・governance status、営業・PoC・契約説明上の no-train 表示。
  - **001（基盤）**: LLM / VLM / Embedding / OCR provider ごとの **no-train 設定の検証**、provider config の保存、provider 監査ログ連携（Base CR-001-B）。
  - 顧客データは opt-in 無しにモデル学習・横断改善・別テナント向け改善に使わない方針を維持する（FR-MFG-016〜018, Hard Rule 7）。

### Functional Requirements — Audit Log Coverage (Product Layer) [CR: Governance]

- **FR-MFG-021**: 以下のイベントを **audit log 対象** としなければならない（基盤 audit/observability [base:FR-016/023] を製品レイヤーへ拡張。基盤側の構造化拡張が要る場合は Base CR-001-A）：
  - document upload / ingest / parse / metadata enrichment（DOCX/XLSX/CSV/PDF/image 取り込みを含む）
  - ManufacturingDocumentMetadata の作成・更新・削除
  - approval_status の変更 / external approval metadata の import
  - DraftArtifact の生成 / review assignment / status transition
  - high-risk query 判定 / SafetyGate の判断 / approved-citation 必須判定 / obsolete・draft 参照時の warning
  - answer generation / citation access / search query / insufficient evidence response
  - feedback / low rating / dashboard access / KPI calculation・export
  - ACL denied / tenant isolation denied
  - admin setting changes / no-train・data retention・provider setting changes
  - deletion / tombstone / cache invalidation
- **FR-MFG-022**: 各 audit log エントリは少なくとも以下を含まなければならない：`tenant_id`・`actor_id`・`actor_role/group`・`app_id/api_client_id`・`action`・`resource_type`・`resource_id`・`decision`・`reason`・`policy_version`・`high_risk_classification_result`・`approval_status_at_use`・`citation_ids/document_ids_used`・`timestamp`・`request_id/trace_id`・`source_ip/client_metadata`(取得可能な範囲)。
- **FR-MFG-023**: audit log には **PII/secret/顧客機密本文を不用意に保存してはならず**、`document_id/chunk_id/citation_id/artifact_id` 等の参照IDで追跡しなければならない。audit log は **改ざん検知・export・retention policy の対象**とし、**tenant をまたいだ参照を禁止**する（基盤 redaction [base:FR-024a] と tenant 分離 [base:FR-021a] を再利用）。

### Non-Functional / Governance Readiness (Design Memo — 将来要件) [CR: Governance]

> MVP で認証取得・完全準拠は約束しない。将来対応を見据えた設計メモ／非機能要件として記録する。

- **FR-MFG-024 (NFR)**: AI事業者ガイドライン等のAIガバナンス文書に沿って、**リスク管理・説明可能性・人間の関与・誤回答対策・データ保護・監査可能性**を説明できる設計とする。**high-risk query・safety gate・draft review・no-train・audit log・groundedness・insufficient evidence response** を AIガバナンス説明の中核機能として扱う。
- **FR-MFG-025 (NFR)**: ISMAP／大企業セキュリティ審査を将来見据え、**暗号化(at rest/in transit)・アクセス制御・監査ログ・脆弱性管理・バックアップ・インシデント対応・データ削除・運用証跡**を設計上の将来要件として記録する（プラットフォーム横断のため Base CR-001-D に委譲、002 では再定義しない）。
- **FR-MFG-026 (NFR)**: MVP では「ISMAP 登録済み／完全準拠」と表現してはならない。MVP では「ISMAP／大企業セキュリティ審査を見据えた設計」として、**証跡・設定・運用資料を整備可能**にする。

### Functional Requirements — PoC v0 / Demo Readiness [CR: Product]

- **FR-MFG-027**: PoC v0（vertical slice）は次を満たさなければならない：PDF/DOCX/XLSX/CSV 取り込み（DOCX/XLSX/CSV=FR-MFG-001, PDF=[base:FR-002]）、製造業メタデータの付与または import（FR-MFG-003/004a）、設備名・アラームコード・工程名・不良種別・部品番号での検索（[base:FR-010] metadata filter）、根拠付き回答 [base:FR-012/013]、根拠不足時は答えない [base:FR-014]、approved/obsolete/draft の扱いを回答に反映（FR-MFG-005/006）、high-risk query では approved document citation 必須（FR-MFG-005/015）、AI生成物は DraftArtifact として作成され自動 approved にならない（FR-MFG-010/010a）、最低限の Web UI または API demo で「質問・回答・引用・文書状態・warning・feedback」を確認可能、PoC KPI を計測可能（FR-MFG-028、詳細は「Product Demo / PoC v0」節）。
- **FR-MFG-028**: システムは次の PoC / 運用 KPI を計測・export できなければならない：`self_resolution_rate`・`average_time_to_answer`・`grounded_answer_rate`・`insufficient_evidence_rate`・`low_rating_rate`・`unanswered_question_count`・`frequently_referenced_documents`・`obsolete_document_candidates`・`expert_interruption_reduction`・**`high_risk_query_count`**・**`safety_gate_block_count`**（FR-MFG-014/030 を具体化、基盤 evaluation/metrics [base:FR-017/026] を利用）。

### Key Entities *(製造業ドメインモデル)*

> いずれも基盤の Document/Chunk/metadata・ACL・tenant に紐づく。`tenant_id` は基盤に従い必須。

- **Factory**: 工場。配下に ProductionLine / Process / Equipment を持つ。ACL/権限領域の単位の一つ。
- **ProductionLine**: 生産ライン。Factory に属し、Process を束ねる。
- **Process**: 工程。`process_name`、関連 Equipment / Part / DefectType を持つ。
- **Equipment**: 設備。`equipment_name`・`model_no`・所属 Line/Process・関連 AlarmCode/WorkInstruction。
- **AlarmCode**: 設備アラーム。`code`・`equipment`・説明・関連 TroubleCase / 対処手順。
- **Product**: 製品。`product_name`・関連 Process / Customer / DefectType。
- **Part**: 部品。`part_no`・関連 Equipment / Product。
- **Customer**: 顧客（機密度高、ACL 対象）。関連 Product / QualityIssue。
- **DefectType**: 不良種別。`defect_name`・関連 Product / Process / QualityIssue。
- **FailureMode**: 故障モード（原因）。TroubleCase の原因として参照。
- **TroubleCase**: 過去トラブル事例。症状・Equipment/Process・FailureMode・Countermeasure・出典文書・発生日。
- **Countermeasure**: 対策。TroubleCase に紐づく。**2軸を持つ**：
  - `type`（表示区分 / evidence の扱い）= reference | candidate（参考/候補。正式手順ではない, FR-MFG-009）。
  - `measure_class`（対策の性質）= provisional（暫定）| permanent（恒久）| unknown（分類不明）。
  - 注: `measure_class=permanent` でも、過去事例由来なら正式作業指示として断定せず「過去事例に基づく候補」として表示する（Hard Rule 4 維持）。
- **WorkInstruction**: 作業標準書。`approval_status`・`effective_date`・関連 Equipment/Process。
- **InspectionChecklist**: 点検表/チェックリスト（取り込み元、またはドラフト生成物=draft）。
- **QualityIssue**: 品質不良レポート。DefectType/Product/Customer・原因・対策・出典。
- **TrainingMaterial**: 教育資料（取り込み元、またはドラフト生成物=draft）。
- **ManufacturingDocumentMetadata**: 文書メタデータの包括型。`equipment`・`model_no`・`alarm_code`・`defect_type`・`process`・`part_no`・`customer`・`document_type`/`document_kind`(work_instruction|inspection|quality_report|trouble_report|minutes|ledger|drawing|training)・`safety_category`・`quality_category`・`equipment_operation_category`・`hazard_tags`・`process_id`・`equipment_id` を保持。承認メタデータ: `approval_status`(draft|pending_review|approved|obsolete)・`effective_date`・`approved_by`・`approved_at`・`obsolete_at`・`superseded_by`・`approval_source`(imported|workflow)。基盤 Document.metadata に格納。
- **DraftArtifact**: AI生成物。`type`(checklist|trouble_report|quality_report|training|**faq**)・`status`(draft|in_review|approved|rejected|archived, 既定 draft)・`source_citations`・`source_document_ids`・`template_id`・`created_by`(生成者)・`reviewer_id`・`reviewer_group/role`・`assigned_at`・`reviewed_at`・`review_comment`・`approval_decision`・`review_status`・`audit_log_ref`（audit trail: 生成時刻/生成者/使用テンプレート/使用文書一覧）。AI が自動 approved にしてはならない。FAQ も含め reviewer の approve まで draft 扱い（正式公開物にしない）。
- **DataUsePolicy** [CR:Governance]: tenant 単位のデータ利用方針。`tenant_id`・`no_train_default`(true 固定既定)・`training_opt_in`(bool, 既定 false)・`opt_in_contract_ref`・`retention_period`・`export_enabled`・`provider_no_train_required`(bool, 既定 true)・`policy_version`・`updated_by`・`updated_at`。no-train/保持/export を営業・管理画面・監査で説明可能にする（FR-MFG-016〜020）。
- **AuditLogEntry** [CR:Governance]: tenant-scoped・tamper-evident な監査記録。`tenant_id`・`actor_id`・`actor_role/group`・`app_id/api_client_id`・`action`・`resource_type`・`resource_id`・`decision`・`reason`・`policy_version`・`high_risk_classification_result`・`safety_block_reason`(approved_citation_missing|insufficient_evidence|other_block, FR-MFG-030)・`approval_status_at_use`・`citation_ids/document_ids_used`・`timestamp`・`request_id/trace_id`・`source_ip/client_metadata`、および集計用 actor 組織コンテキスト `factory_id`・`department_id`（部署=base ACL group/role 由来、工場=Factory 由来）。PII/secret/機密本文は保存せず参照IDで追跡（FR-MFG-021〜023）。改ざん検知・export・retention・tenant 越え参照禁止。

## Success Criteria *(mandatory)* — PoC KPI

- **SC-MFG-001**: **自己解決率** — 現場ユーザーが追加問い合わせなしに回答で解決できた割合を計測でき、PoC 期間で baseline 比改善を確認できる。
- **SC-MFG-002**: **回答時間削減** — 質問から根拠付き回答までの所要時間（p50/p95）を計測でき、従来の人手照会比で短縮を示せる。
- **SC-MFG-003**: **問い合わせ削減** — 有識者/保全への直接問い合わせ件数の減少を計測できる。
- **SC-MFG-004**: **根拠付き回答率** — 回答のうち引用つき（かつ安全/品質/設備操作は承認済み引用）である割合を計測でき、目標水準を満たす。
- **SC-MFG-005**: **未回答質問数** — 根拠不足で答えられなかった質問を記録・集計でき、ナレッジ不足領域を特定できる。
- **SC-MFG-006**: 安全/品質/設備操作の回答で、承認済み文書の引用が無いまま断定する件数が **0**（safety hard rule, FR-MFG-005/007）。
- **SC-MFG-007**: AI 生成物（報告書/チェックリスト/教育資料）が `draft` 以外の確定状態で自動確定される件数が **0**（必ず人間レビュー前提）。
- **SC-MFG-008**: 権限外（工場/部署/役職/設備領域）ユーザーへ機密文書（顧客名・不良・図面等）が漏洩する件数が **0**（基盤 ACL hard gate [base:SC-004] を継承）。
- **SC-MFG-009** [CR:Governance]: 顧客データが tenant admin の opt-in 無しにモデル学習・モデル改善（横断/別テナント含む）へ利用される件数が **0**（no-train, FR-MFG-016〜018）。
- **SC-MFG-010** [CR:Governance]: 規定の監査イベント（approval transition / DraftArtifact review / high-risk decision / safety gate decision / answer generation / citation access / ACL denial / tenant isolation denial / no-train・retention setting change）が audit log に欠落なく記録される（記録率 **100%**、欠落 0; FR-MFG-021〜023）。監査ログに PII/secret/機密本文が混入する件数 **0**。
- **SC-MFG-011** [CR:Governance]: obsolete / draft 文書を正式根拠として断定回答に使用する件数が **0**（FR-MFG-006。SC-MFG-006 の「approved 引用欠如での断定」とは別観点）。
- **SC-MFG-012** [CR:Product]: PoC dashboard または KPI API で、未回答・低評価・頻出質問・参照文書・自己解決率を確認でき、FR-MFG-028 の全 KPI を計測・export できる。
- **SC-MFG-013** [CR:G2/G3]: ダッシュボード/KPI API で **`high_risk_query_count` と `safety_gate_block_count`**（内訳含む）を tenant/collection/factory/department/time range で確認・export できる（FR-MFG-030）。安全制御が「効いている件数」を運用者が可視化できる。

## Assumptions

- 基盤 `001-rag-platform` の tenant/ACL/citation/groundedness/evaluation/cost/visual RAG が利用可能で、本 layer はその上に構築する（再定義しない）。
- DOCX/XLSX/CSV parser は基盤 Parser 抽象に追加実装する（基盤の差し替え可能性を利用）。
- 製造業メタデータは基盤 Document/Chunk の metadata に格納し、検索 metadata filter とACLで利用する。
- `approval_status`/`effective_date` は本 layer のメタデータとして保持・識別する。完全な DMS・任意バージョン rollback は提供しない（非ゴール）。
- KPI は 001 と同様、初回 baseline を確立し PoC 期間で baseline 比を評価する（絶対目標は PoC 計画で設定）。
- 安全・品質・設備操作の判定は人間レビュー前提で、AIは draft/参考提示にとどまる。

## Dependencies

- **001-rag-platform**（必須）: 認証/テナント/ACL、ingestion/検索/回答/引用/根拠不足、削除(tombstone)、evaluation/cost/observability、visual RAG（OCR/visual citation）、parser abstraction。
- 文書の承認状態は、取り込み元または管理者が付与する（本 layer はその識別を必須化。Q1=軽量WF＋imported approval で解決済）。
- **[CR:Governance] provider no-train mode**: 外部 LLM/VLM/Embedding/OCR provider が no-train mode/契約を提供すること（基盤 provider 抽象の no-train capability に依存。Base CR-001-B）。
- **[CR:Governance] base audit/retention/export**: 構造化 audit・retention・export は基盤拡張に依存（Base CR-001-A / C）。プラットフォーム横断のセキュリティ NFR は Base CR-001-D。

## Out of Scope (非ゴール)

- 設備制御システムとの直接連携。
- 作業指示の自動確定（ドラフトのみ、人間レビュー必須）。
- 人間レビューなしの品質判定 / 法規制・安全基準の最終判断自動化。
- 音声RAG / 動画RAG。
- フル DMS / 任意バージョン rollback（latest_approved / obsolete / effective_date の識別は必須だが、版の復元は対象外）。
- **電子署名**（軽量レビューのみ。法的電子署名は対象外）。[CR:Governance]
- **ISMAP 取得そのもの / 完全準拠の保証**（「見据えた設計」までが MVP 範囲）。[CR:Governance]
- **顧客データの無断学習利用**（no-train by default。opt-in＋別契約なしの学習・改善利用は禁止）。[CR:Governance]

## Hard Rules（非交渉。Q1/Q2/Q3 の決定に基づく）

1. **AI生成物は自動確定しない。** 必ず `draft` で作成し、reviewer のレビュー無しに確定版にしない（FR-MFG-010/010a, SC-MFG-007）。
2. **safety / quality / equipment operation / dangerous work（high-risk query）に関する回答では、`approved` かつ有効な文書の引用が無い限り断定しない**（FR-MFG-005/007/015, SC-MFG-006）。
3. **draft / obsolete 文書は policy で許可された場合のみ参考情報として使え、正式根拠にしない。** obsolete は warning 表示必須（FR-MFG-006）。
4. **過去トラブル報告に基づく対策は、正式手順ではなく候補・参考・過去事例として表示する**（FR-MFG-008/009）。
5. **承認状態・reviewer・判断理由・使用根拠・生成物の状態遷移を audit log に残す**（FR-MFG-010b, [base:FR-016/023]）。
6. **フルDMS・複雑な承認経路・電子署名・任意版rollback は MVP 対象外**（FR-MFG-004a, 非ゴール）。
7. **顧客データは opt-in 無しにモデル学習・改善へ使用しない（no-train by default）。** 外部 provider も no-train mode 前提（FR-MFG-016〜018, SC-MFG-009）。[CR:Governance]
8. **規定の監査イベントは tenant-scoped・tamper-evident な audit log に記録し、PII/secret/機密本文を保存せず参照IDで追跡する。** tenant 越え参照は禁止（FR-MFG-021〜023, SC-MFG-010）。[CR:Governance]
9. **MVP で「ISMAP 登録済み／完全準拠」と表現しない。** ISMAP/大企業審査を「見据えた設計」とし、証跡・運用資料を整備可能にする（FR-MFG-025/026）。[CR:Governance]

すべての Open Question（Q1/Q2/Q3）は解決済み（上記 Clarifications 参照）。Governance CR の未解決2件は本ファイルの「Open Questions (Governance CR)」を参照。

## Base Change Requests for 001-rag-platform [横断要件。002 では再定義せず基盤側へ]

> 002 は基盤を再定義しない。製品レイヤーの要件達成に基盤 001 の拡張が必要な点を以下に列挙する
> （001 の spec/plan に取り込む際の入口）。

- **Base CR-001-A (Audit / Observability 拡張)**: 001 の audit/trace [FR-016/023] を、構造化 `AuditLogEntry` スキーマ・**tamper-evidence（hash chain 等）**・export・retention policy・tenant 越え参照禁止 へ拡張し、製品レイヤーの監査イベント（FR-MFG-021）を基盤で一貫記録できるようにする。
- **Base CR-001-B (Provider no-train capability and configuration verification)**: LLM/VLM/Embedding/OCR provider 抽象 [FR-031] に **data-use mode / no-train capability**（宣言・強制・**検証**用 capability metadata）を追加し、provider ごとの **no-train 設定の検証・provider config 保存・provider 監査ログ連携** を基盤側で担えるようにする。no-train 非対応 provider を既定で利用不可にできる（FR-MFG-017/029。責務境界: 002=policy/opt-in/governance表示、001=provider設定検証/保存/監査）。
- **Base CR-001-C (Data retention / export)**: 基盤 data lifecycle [FR-007/008] に **tenant データ export** と **設定可能な retention policy** を追加（削除 tombstone は既存再利用; FR-MFG-020）。
- **Base CR-001-D (Platform security NFR)**: 暗号化(at rest/in transit)・脆弱性管理・バックアップ・インシデント対応 を基盤の非機能要件として整備（ISMAP/大企業審査の将来要件; FR-MFG-025）。

## Product Demo / PoC v0 (Vertical Slice) [CR: Product]

PoC 営業で最初に見せる縦切り。範囲は **FR-MFG-027/028** に準拠：

- 取り込み: PDF / DOCX / XLSX / CSV（画像/スキャンは基盤 visual RAG を任意で）。
- メタデータ: 製造業メタデータの付与 or import（設備名/型番/アラームコード/不良種別/工程名/部品番号/顧客名）。
- 検索: 設備名・アラームコード・工程名・不良種別・部品番号で metadata filter 検索。
- 回答: 根拠付き回答／根拠不足は答えない／approved・obsolete・draft の扱いを回答へ反映／obsolete warning／high-risk は approved citation 必須。
- 生成: AI生成物は DraftArtifact（自動 approved にならない、reviewer 導線）。
- UI: 最低限の Web UI または API demo（質問・回答・引用・文書状態・warning・feedback を確認）。
- 計測: PoC KPI（`self_resolution_rate` / `average_time_to_answer` / `grounded_answer_rate` / `insufficient_evidence_rate` / `low_rating_rate` / `unanswered_question_count` / `frequently_referenced_documents` / `obsolete_document_candidates` / `expert_interruption_reduction`）。

## Open Questions (Governance CR — 解決済み, Session 2026-06-19 @ /speckit-plan)

- **GQ1 [no-train フォールバック]** → **解決: (a) block（既定で利用不可）**。ある capability に no-train を保証できる provider が存在しない場合、その capability は既定で **利用不可（block）** とする。tenant admin による opt-in 上書きは MVP では提供しない（no-train by default / Hard Rule 7 を最も保守的に充足）。block 時は `temporarily_unavailable`（capability 由来）として扱い、断定回答を返さない。`FR-MFG-017` を本決定で確定。
- **GQ2 [retention 既定値]** → **解決: 顧客データ=既定 1 年 / 監査ログ=既定 1 年**。`DataUsePolicy.retention_period` の既定は顧客データ 365 日・監査ログ 365 日とし、tenant 単位で上書き可能（上書き下限は法令・運用上の最小値、上限は tenant 契約に従う。MVP では下限 30 日・上限 3650 日を許容範囲のガイドとする）。retention 失効分は基盤 tombstone/カスケード [base:FR-008] と Base CR-001-C（retention/export）で削除する。`FR-MFG-020` を本決定で確定。
