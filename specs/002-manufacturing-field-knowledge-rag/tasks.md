# Tasks: Manufacturing Field Knowledge RAG (Solution Layer)

**Input**: Design documents from `specs/002-manufacturing-field-knowledge-rag/`

**Prerequisites**: plan.md, spec.md (required); research.md, data-model.md, contracts/ (mfg-openapi.md, mfg-interfaces.md), quickstart.md

**Tests**: spec/plan が safety hard-gate（SC-MFG-006/007/008/009/010/011）・contract・PoC KPI を明示要求するためテストタスクを含む。

> **Ledger (2026-06-20)**: 完了タスクは `[x]`。本番アダプタ track（T007）と Dagster/sync-status/KPI/eval track（T011a/T024a/T031a/T031b/T047a/T051a/T071/T071a）は、001 control-plane と PostgreSQL migration/RLS 契約を再利用する製造業専用薄層として実装済み。T072 は `poc-ui/` stdlib デモで対応。実装は GitHub `wer-inc/raku-rag` の 12+ コミットを正本とする。

**Base/framework reuse (do NOT redefine)**: 001-rag-platform（tenant 分離・ACL pre-filter・ingestion/diff-sync/backfill/evaluation/KPI materialization state・retrieval・answer・citation・groundedness・deletion(tombstone)・cost・observability・visual RAG・13 抽象）と 010-industry-solution-framework（IndustryProfile / MetadataSchema / RiskPolicy / DraftArtifact / KPI / Dashboard contract）を再利用する。AWS MVP の ingestion は SQS worker、Dagster は optional control plane 互換として扱う。本 layer は 001/010 の上に `src/raku_rag/manufacturing/` パッケージとして構築し、parser のみ 001 `providers/parsers.py` に追加する。

**Organization**: User Story 単位。canonical 語 = **manufacturing metadata**（001 `Document.metadata` 格納）, **approval_status**(draft|pending_review|approved|obsolete), **DraftArtifact**(status 既定 draft), **high-risk query**, **SafetyGate**, **safety_block_reason**(approved_citation_missing|insufficient_evidence|other_block 相互排他), **DataUsePolicy**, **AuditLogEntry**。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 並列可（別ファイル・依存なし）／ **[Story]**: US1〜US6（Setup/Foundational/Governance/Polish は無し）／ 各タスクにファイルパス

## Path Conventions

Web-service モジュラモノリス（plan.md）: 002 solution layer = `src/raku_rag/manufacturing/`, tests = `tests/manufacturing/`。parser 追加のみ `src/raku_rag/providers/parsers.py`。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 製造業 solution layer のパッケージ構造と依存・CI ゲート初期化（001 基盤は既存）

- [x] T001 Create solution-layer package structure `src/raku_rag/manufacturing/{domain,safety,ingestion,knowledge,drafts,governance,telemetry,kpi,api}` と `tests/manufacturing/` per plan.md（各 `__init__.py` 含む）
- [x] T002 Add parser dependencies to `pyproject.toml`: `python-docx`（DOCX）, `openpyxl`（XLSX）。CSV は stdlib。製造業 layer の optional-deps group として分離
- [x] T003 [P] Add manufacturing sample fixtures（承認済み DOCX マニュアル・XLSX/CSV 台帳・スキャン点検表・過去トラブル報告・obsolete 文書・draft 文書）in `tests/manufacturing/fixtures/`
- [x] T004 [P] Extend CI pipeline with **manufacturing safety hard-gate** stage（SC-MFG-006/007/008/009/010/011 を baseline 不問の absolute gate として実行）in `.github/workflows/ci.yml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 全 User Story が依存する製造業ドメインモデル・mfg 抽象・audit/policy/ACL マッピング基盤

**⚠️ CRITICAL**: 完了まで User Story 着手不可

- [x] T005 Define manufacturing metadata + domain entity schemas (Pydantic) in `src/raku_rag/manufacturing/domain/metadata.py`, `src/raku_rag/manufacturing/domain/entities.py` — ManufacturingDocumentMetadata（製造業タグ・safety/quality 分類・承認メタデータ approval_status/effective_date/approved_by/approved_at/obsolete_at/superseded_by/approval_source）, Factory/ProductionLine/Process/Equipment/AlarmCode/Product/Part/Customer/DefectType/FailureMode/TroubleCase/Countermeasure(**type + measure_class 2 軸**)/WorkInstruction/InspectionChecklist/QualityIssue/TrainingMaterial。全エンティティ `tenant_id` 必須（data-model.md §B/§C/§D）
- [x] T006 Define DraftArtifact / DataUsePolicy / AuditLogEntry / SafetyDecision / HighRiskClassification schemas in `src/raku_rag/manufacturing/domain/draft.py`, `policy.py`, `audit.py` — DraftArtifact(status 既定 draft, reviewer/audit trail fields), DataUsePolicy(no_train_default=true/training_opt_in=false/provider_no_train_required=true/no_train_fallback=block/retention 365/365), AuditLogEntry(参照ID・factory_id/department_id・safety_block_reason・high_risk_classification_result), SafetyDecision/HighRiskClassification value objects（data-model.md §E/§F/§G/§H）
- [x] T007 SQLAlchemy models + Alembic migration for manufacturing tables in `src/raku_rag/persistence/manufacturing_models.py`, `migrations/` — 全テーブル `tenant_id` 必須・001 ACL/tombstone 従属・tenant 越え参照禁止索引。manufacturing metadata は 001 `Document.metadata`(JSON) 格納方針（data-model.md §A/§B）(depends T005, T006)
- [x] T008 [P] Define manufacturing abstract interfaces in `src/raku_rag/manufacturing/interfaces.py` — MetadataEnricher, ApprovalWorkflow, HighRiskClassifier, SafetyGate, TroubleCaseRetriever, DraftGenerator, ReviewWorkflow, DataUsePolicyStore, NoTrainGuard, RetentionManager, AuditLogWriter, SafetyTelemetry（contracts/mfg-interfaces.md）
- [x] T009 Implement AuditLogWriter core（tenant-scoped・**参照IDのみ（PII/secret/本文非保存）**・001 Redactor 再利用・tenant 越え参照禁止）in `src/raku_rag/manufacturing/domain/audit.py` (depends T006, T008) — telemetry/KPI の単一真実源（FR-MFG-021/022/023, SC-MFG-010）
- [x] T010 Implement DataUsePolicyStore + 既定 seed（no_train_default=true, training_opt_in=false, provider_no_train_required=true, no_train_fallback=block, retention_customer=365, retention_audit=365）in `src/raku_rag/manufacturing/governance/no_train.py` (depends T006, T008) — GQ1/GQ2 確定値
- [x] T011 Implement ACL mapping helper（部署=001 ACL group/role, 工場=Factory, 役職=role, 設備領域=Process/Equipment metadata; **新規認可機構を作らず** 001 AclPolicy/visibility_filter を再利用）in `src/raku_rag/manufacturing/domain/acl_mapping.py` (depends T005) — FR-MFG-013

- [x] T011a [P] Define manufacturing Dagster integration hooks in `src/raku_rag/dagster/assets/manufacturing.py`, `src/raku_rag/dagster/checks/manufacturing.py` — `manufacturing_metadata_enriched_elements`, approval_metadata_checksum observation, KPI materialization resources。online answer/search/Draft/review state machine からは Dagster を呼ばない（depends T005, T006, T008）

**Checkpoint**: 製造業ドメイン・mfg 抽象・audit/policy/ACL マッピング基盤完成（001 基盤の上に従属）

---

## Phase 3: User Story 1 - 現場担当者が根拠付きで即答を得る (Priority: P1) 🎯 MVP

**Goal**: 製造業メタデータ付き検索→根拠付き回答に **high-risk safety gate** を上乗せ（approved かつ有効な引用必須、obsolete/draft は正式根拠にしない、根拠不足は推測しない）。

**Independent Test**: seed 済み承認文書で (a) アラームコード質問→approved 引用付き回答、(b) 安全根拠の無い危険作業質問→断定せず insufficient（safety）。

### Tests for User Story 1 ⚠️

- [x] T012 [P] [US1] Contract test `POST /v1/answer`（manufacturing 拡張: high_risk/safety_block_reason/obsolete_warning/requires_onsite_confirmation, citation の approval_status/effective_date）in `tests/manufacturing/test_answer_contract.py`（contracts/mfg-openapi.md §A）
- [x] T013 [P] [US1] Integration: 承認済みマニュアルに答えのある質問 → `ok` + approved 引用 + used_chunks in `tests/manufacturing/test_grounded_answer.py`（quickstart S2, US1-1）
- [x] T014 [P] [US1] **Safety hard-gate（SC-MFG-006）**: high-risk × approved/有効引用欠如 → 断定しない（`insufficient_evidence`, `safety_block_reason=approved_citation_missing`）in `tests/manufacturing/test_safety_gate.py`（quickstart S3, US1-2, FR-MFG-005/007）
- [x] T015 [P] [US1] **Safety hard-gate（SC-MFG-011）**: 根拠が obsolete のみ→一次根拠にせず obsolete_warning、draft のみ→正式根拠にしない in `tests/manufacturing/test_obsolete_draft_evidence.py`（quickstart S4, US1-3, FR-MFG-006）

### Implementation for User Story 1

- [x] T016 [US1] Implement HighRiskClassifier（**3 段カスケード**: metadata 分類タグ → ルール+キーワード意図 → 曖昧時のみ 001 LLMProvider 分類, **OR 判定・迷えば high-risk**, reason_codes/classification_source 返却）in `src/raku_rag/manufacturing/safety/classifier.py` (depends T008) — FR-MFG-015, research R2
- [x] T017 [US1] Implement SafetyGate（001 GroundednessGate **後段に 1 段上乗せ**: approved∧有効引用必須・obsolete_warning・requires_onsite_confirmation・`safety_block_reason` を **相互排他 1 コードに正規化**（approved_citation_missing→insufficient_evidence→other_block）・approval_status_at_use 記録）in `src/raku_rag/manufacturing/safety/gate.py` (depends T016) — FR-MFG-005/006/007/030, research R3
- [x] T018 [US1] Extend AnswerService for manufacturing（001 answer 経路に HighRiskClassifier→SafetyGate を結線, manufacturing_filters を 001 metadata filter へ写像, citation に approval_status/effective_date/approval_source 付与, manufacturing レスポンスブロック）in `src/raku_rag/manufacturing/api/answer_ext.py` (depends T016, T017, T011)
- [x] T019 [US1] Extend search で製造業 metadata filter + approval_status/effective_date を結果に付与、XLSX/CSV はセル座標(sheet/row/col)を引用範囲に in `src/raku_rag/manufacturing/api/search_ext.py` (depends T011) — FR-MFG-002/003, US2-2 連携
- [x] T020 [US1] Record high-risk 判定 / SafetyGate 判断 / approved-citation 必須判定 / obsolete・draft warning を AuditLogEntry に記録 in `src/raku_rag/manufacturing/api/answer_ext.py` (depends T009, T018) — FR-MFG-021
- [x] T021 [US1] Wire `/v1/answer` & `/v1/search` manufacturing router（001 router に拡張フィールドを加算のみ・既存契約非破壊）in `src/raku_rag/manufacturing/api/__init__.py` (depends T018, T019)

**Checkpoint**: US1 が seed データで独立機能（製造業メタ検索・approved 引用必須・obsolete/draft 安全側・根拠不足）

---

## Phase 4: User Story 2 - 製造業ドキュメントの取り込みとメタデータ付与 (Priority: P1) 🎯 MVP

**Goal**: DOCX/XLSX/CSV/PDF/画像 を取り込み、製造業メタデータ・承認メタデータ（軽量ワークフロー＋imported approval）を付与。

**Independent Test**: 各形式取り込み→正規化・index 化、製造業メタデータと approval_status/effective_date が検索フィルタ・引用に反映。

### Tests for User Story 2 ⚠️

- [x] T022 [P] [US2] Integration: DOCX/XLSX/CSV 取り込み → 正規化・チャンク・index 化（001 ingestion 再利用）in `tests/manufacturing/test_ingest_formats.py`（quickstart S1, US2-1, FR-MFG-001）
- [x] T023 [P] [US2] Integration: XLSX/CSV のセル参照が引用範囲(sheet/row/col)として保持・解決される in `tests/manufacturing/test_cell_citation.py`（US2 edge, FR-MFG-002）
- [x] T024 [P] [US2] Integration: approval_status/effective_date 設定 → latest_approved/obsolete/有効日が検索・回答で識別、imported approval が source of truth として優先 in `tests/manufacturing/test_approval_lifecycle.py`（US2-2, FR-MFG-004/004a）

- [x] T024a [P] [US2] Contract test: manufacturing sync/status APIs (`POST /v1/manufacturing/sources/{source_id}/sync`, `GET /v1/manufacturing/sources/{source_id}/sync-status`, `GET /v1/manufacturing/ingestion-runs/{ingestion_run_id}`) in `tests/manufacturing/test_sync_status_contract.py` — Dagster run fields are internal-operator only

### Implementation for User Story 2

- [x] T025 [P] [US2] Implement DocxParser（001 `Parser` 実装: 段落/表を正規化テキスト化）in `src/raku_rag/providers/parsers.py` — FR-MFG-001, research R1
- [x] T026 [P] [US2] Implement SpreadsheetParser（XLSX/CSV; 行/列/シート保持, **`sheet!R{row}C{col}` セルアンカー**で 001 offset_mapping をセル座標へ写像）in `src/raku_rag/providers/parsers.py` — FR-MFG-002, research R1
- [x] T027 [US2] Implement MetadataEnricher（ingest 時に製造業メタデータ・承認メタデータを 001 `Document.metadata` へ付与, `Chunk.metadata` 継承伝播）in `src/raku_rag/manufacturing/ingestion/metadata_enrichment.py` (depends T005, T008) — FR-MFG-003
- [x] T028 [US2] Implement ApprovalWorkflow（軽量 draft→pending_review→approved→obsolete + import_external で imported approval を source of truth 化, 全 transition を audit）in `src/raku_rag/manufacturing/ingestion/approval.py` (depends T009, T027) — FR-MFG-004/004a
- [x] T029 [US2] Extend `POST /v1/ingest` で manufacturing_metadata/approval 受理 + DOCX/XLSX/CSV 形式（001 非同期 ingestion 再利用, 画像/スキャンは 001 visual RAG 再利用）in `src/raku_rag/manufacturing/api/ingest_metadata.py` (depends T025, T026, T027)
- [x] T030 [US2] Implement `PUT /v1/manufacturing/documents/{id}/metadata` & `POST .../approval`（metadata 更新・承認遷移・external import）in `src/raku_rag/manufacturing/api/ingest_metadata.py` (depends T028)
- [x] T031 [US2] Record document ingest/parse/metadata enrichment/approval transition/external import を AuditLogEntry に記録 in `src/raku_rag/manufacturing/ingestion/metadata_enrichment.py` (depends T009) — FR-MFG-021

- [x] T031a [US2] Implement Dagster `manufacturing_metadata_enriched_elements` asset hook — parsed elements/chunks に ManufacturingDocumentMetadata と approval metadata を付与し、`approval_metadata_checksum` のみ変化時は metadata + safety/index filter update のみにする in `src/raku_rag/dagster/assets/manufacturing.py`, `src/raku_rag/manufacturing/ingestion/metadata_enrichment.py` (depends T011a, T027, T028)
- [x] T031b [US2] Implement manufacturing sync/status routers in `src/raku_rag/manufacturing/api/ingest_metadata.py` — SourceSyncState / IngestionRun / DocumentProcessingState を表示し、内部運用者ロールのみ dagster_run_id / run URL を返す（depends T024a, 001 status API）

**Checkpoint**: US1+US2 で「製造業文書取り込み＋メタデータ/承認 → 安全側回答」のフルパス成立（PoC コア）

---

## Phase 5: User Story 3 - 過去トラブルの類似事例・原因・対策の一覧化 (Priority: P2)

**Goal**: 症状クエリ→類似 TroubleCase（原因 FailureMode・対策 Countermeasure・再発防止）一覧、対策は暫定/恒久を分離し候補・参考表示。

**Independent Test**: 症状クエリ→類似 TroubleCase 一覧（原因/対策/再発防止/引用）、暫定/恒久分離、permanent でも候補ラベル。

### Tests for User Story 3 ⚠️

- [x] T032 [P] [US3] Contract test `POST /v1/manufacturing/trouble-cases/search`（provisional/permanent 分離, label 候補・参考, citation approval_status）in `tests/manufacturing/test_trouble_cases_contract.py`（contracts/mfg-openapi.md §C）
- [x] T033 [P] [US3] Integration: 「振動増加＋異音」→類似 TroubleCase（FailureMode/Countermeasure/再発防止/引用）, **暫定/恒久に分けて表示**, ACL 権限外事例は出ない in `tests/manufacturing/test_trouble_cases.py`（quickstart S5, US3-1, FR-MFG-008）

### Implementation for User Story 3

- [x] T034 [P] [US3] Persist/seed manufacturing knowledge graph relations（TroubleCase↔FailureMode↔Countermeasure↔Document）in `src/raku_rag/persistence/manufacturing_models.py` (depends T007)
- [x] T035 [US3] Implement TroubleCaseRetriever（001 retrieval[ACL pre-filter]で TroubleCase 由来 Chunk 取得→エンティティ解決→FailureMode/Countermeasure/再発防止一覧）in `src/raku_rag/manufacturing/knowledge/trouble_cases.py` (depends T034, T011) — FR-MFG-008
- [x] T036 [US3] Implement Countermeasure 2 軸表示正規化（type=reference|candidate × measure_class=provisional|permanent|unknown; **permanent でも過去事例由来は「過去事例に基づく候補・参考」に正規化**, 暫定/恒久分離）in `src/raku_rag/manufacturing/knowledge/trouble_cases.py` (depends T035) — FR-MFG-009, Hard Rule 4, research R6
- [x] T037 [US3] Implement `POST /v1/manufacturing/trouble-cases/search` router + answer generation / citation access の audit 記録 in `src/raku_rag/manufacturing/api/trouble.py` (depends T035, T036, T009)

**Checkpoint**: 類似トラブル事例が原因/対策/再発防止つきで一覧化、暫定/恒久分離・候補表示・ACL 適用

---

## Phase 6: User Story 4 - ドラフト生成（チェックリスト/報告書/教育資料/FAQ） (Priority: P2)

**Goal**: 点検チェックリスト・トラブル報告書・品質報告・教育資料・FAQ の **ドラフト** 生成（必ず draft・引用付き・人間レビュー前提）と軽量レビュー導線。

**Independent Test**: チェックリスト生成→`draft`・引用付き・レビュー必須表示、FAQ も自動 approved にならない、reviewer approve まで draft。

### Tests for User Story 4 ⚠️

- [x] T038 [P] [US4] Contract test `POST /v1/manufacturing/drafts` & `/assign` & `/review`（status=draft 固定, reviewer 遷移）in `tests/manufacturing/test_drafts_contract.py`（contracts/mfg-openapi.md §D）
- [x] T039 [P] [US4] **Safety hard-gate（SC-MFG-007）**: AI 生成物が `draft` 以外で自動確定されない（`created_by=ai` の自動 approved 拒否）, FAQ も draft 扱い, approved は reviewer のみ in `tests/manufacturing/test_draft_only.py`（quickstart S6, US4-1/3, FR-MFG-010, Hard Rule 1）
- [x] T040 [P] [US4] Integration: トラブル報告書/FAQ draft 生成 → source_citations/source_document_ids 付き, 未確定事項を draft 上で明示, 安全項目は approved 根拠が無ければ断定しない in `tests/manufacturing/test_draft_generation.py`（US4-2/3, FR-MFG-011）

### Implementation for User Story 4

- [x] T041 [US4] Implement DraftGenerator（kind=checklist|trouble_report|quality_report|training|faq; **必ず status=draft**, source_citations/source_document_ids/template_id/created_by/audit_log_ref 付与, 安全項目は FR-MFG-005 準拠で断定しない）in `src/raku_rag/manufacturing/drafts/generator.py` (depends T006, T017) — FR-MFG-010/011, G1
- [x] T042 [US4] Implement ReviewWorkflow（draft→in_review→approved/rejected/archived, reviewer_id/role/group・assigned_at・reviewed_at・review_comment・approval_decision; approved は reviewer 判断のみ・多段承認/電子署名なし）in `src/raku_rag/manufacturing/drafts/review.py` (depends T006) — FR-MFG-010a
- [x] T043 [US4] Implement `POST /v1/manufacturing/drafts`, `/assign`, `/review`, `GET /{id}` routers in `src/raku_rag/manufacturing/api/drafts.py` (depends T041, T042)
- [x] T044 [US4] Record DraftArtifact 生成 / review assignment / status transition を AuditLogEntry に記録（audit trail: 生成時刻/生成者/テンプレート/使用文書一覧）in `src/raku_rag/manufacturing/drafts/generator.py`, `review.py` (depends T009) — FR-MFG-010b, Hard Rule 5
- [x] T045 [US4] Wire DraftArtifact 由来 InspectionChecklist/TrainingMaterial を draft として entities に接続 in `src/raku_rag/manufacturing/domain/entities.py` (depends T041)

**Checkpoint**: 5 種ドラフトが draft 限定で生成・レビュー導線で確定、自動 approved なし、全 transition 監査

---

## Phase 7: User Story 5 - 管理者によるナレッジ運用ダッシュボード (Priority: P3)

**Goal**: 未回答/低評価/頻出質問/頻出文書/古い文書/ナレッジ不足 ＋ **Safety Telemetry**（high_risk_query_count・safety_gate_block_count 内訳）を集計表示。

**Independent Test**: ダッシュボードで運用指標と Safety Telemetry が tenant/collection/factory/department/time range で集計表示。

### Tests for User Story 5 ⚠️

- [x] T046 [P] [US5] Contract test `GET /v1/manufacturing/dashboard`, `/safety-telemetry`, `/kpi`（source=audit_log, breakdown 相互排他）in `tests/manufacturing/test_dashboard_contract.py`（contracts/mfg-openapi.md §E）
- [x] T047 [P] [US5] **Telemetry hard-gate（SC-MFG-013）**: `safety_gate_block_count` 内訳（approved_citation_missing/insufficient_evidence/other_block）が **相互排他・1 ブロック 1 コード**、audit 由来で二重カウントなし、factory/department 軸集計 in `tests/manufacturing/test_safety_telemetry.py`（quickstart S10, US5-2, FR-MFG-030）

- [x] T047a [P] [US5] Integration: Dagster `manufacturing_dashboard_metrics` daily/manual materialization updates PostgreSQL result with `materialized_at` and dashboard reads it without calling Dagster in request path in `tests/manufacturing/test_kpi_materialization.py`

### Implementation for User Story 5

- [x] T048 [US5] Implement SafetyTelemetry 集計（**audit log を単一真実源**として high_risk_query_count / safety_gate_block_count[内訳] を tenant/collection/factory/department/time_range[hourly/daily/custom] で集計, retention は DataUsePolicy 準拠）in `src/raku_rag/manufacturing/telemetry/safety_metrics.py` (depends T009) — FR-MFG-030, G2/G3
- [x] T049 [US5] Implement PoC KPI 計測・export（self_resolution_rate/average_time_to_answer/grounded_answer_rate/insufficient_evidence_rate/low_rating_rate/unanswered_question_count/frequently_referenced_documents/obsolete_document_candidates/expert_interruption_reduction/high_risk_query_count/safety_gate_block_count, 001 evaluation/metrics 再利用）in `src/raku_rag/manufacturing/kpi/poc_metrics.py` (depends T009) — FR-MFG-014/028
- [x] T050 [US5] Implement knowledge-ops dashboard 集計（未回答/低評価/頻出質問/頻出文書/obsolete候補/ナレッジ不足, 001 feedback/observability 集計）in `src/raku_rag/manufacturing/telemetry/safety_metrics.py` (depends T009) — FR-MFG-012, US5-1
- [x] T051 [US5] Implement `GET /v1/manufacturing/dashboard`, `/safety-telemetry`, `/kpi`(format=json|csv) routers + dashboard access / KPI calc・export の audit 記録 in `src/raku_rag/manufacturing/api/dashboard.py` (depends T048, T049, T050) — request path は PostgreSQL materialized KPI を読み、Dagster を同期呼び出ししない
- [x] T051a [US5] Implement Dagster `manufacturing_dashboard_metrics` asset + daily schedule/manual refresh in `src/raku_rag/dagster/assets/manufacturing.py`, `src/raku_rag/dagster/jobs/manufacturing_kpi.py` — PoC KPI / safety telemetry を materialize し、`materialized_at`, `source_ingestion_run_id`, `dagster_run_id?` を保存（depends T047a, T048, T049）

**Checkpoint**: 運用ダッシュボードと Safety Telemetry が集計表示、安全制御の「効いている件数」を可視化

---

## Phase 8: User Story 6 - 部署/工場/役職/設備領域ごとのアクセス制御 (Priority: P2)

**Goal**: 部署/工場/役職/設備領域ごとのアクセス制御（**新規認可機構を作らず** 001 ACL pre-filter へのマッピング）。

**Independent Test**: 工場A保全の権限で工場B品質の文書/顧客名/不良/図面が検索・回答・引用・類似事例に出ない。

### Tests for User Story 6 ⚠️

- [x] T052 [P] [US6] **Security hard-gate（SC-MFG-008）**: 権限外（工場/部署/役職/設備領域）ユーザーへ機密文書（顧客名・不良・図面）が search/answer/citation/trouble-cases/draft に出ない、tenant 越え参照拒否 in `tests/manufacturing/test_acl_mapping.py`（quickstart S7, US6-1, FR-MFG-013, 001 FR-022 継承）

### Implementation for User Story 6

- [x] T053 [US6] Finalize ACL mapping enforcement across all manufacturing endpoints（answer/search/trouble-cases/drafts/dashboard が T011 mapping helper を経由し 001 AclPolicy visibility_filter を強制）in `src/raku_rag/manufacturing/domain/acl_mapping.py` (depends T011, T021, T037, T043, T051)
- [x] T054 [P] [US6] Apply ACL mapping to manufacturing entities（Factory/Process/Equipment/Customer の機密度に応じた scope, Customer は ACL 対象）in `src/raku_rag/manufacturing/domain/entities.py` (depends T011)
- [x] T055 [US6] Record ACL denied / tenant isolation denied を AuditLogEntry に記録 in `src/raku_rag/manufacturing/domain/acl_mapping.py` (depends T009) — FR-MFG-021
- [x] T056 [US6] Seed factory/department actor 組織コンテキスト（factory_id/department_id）を AuditLogEntry に伝播（safety telemetry 集計軸用）in `src/raku_rag/manufacturing/domain/audit.py` (depends T009, T011) — FR-MFG-030

**Checkpoint**: 製造業スコープの ACL マッピングが全エンドポイントで強制、権限外漏洩 0（001 hard gate 継承）

---

## Phase 9: Governance & Product Readiness Overlay (Cross-Cutting)

**Purpose**: no-train / audit coverage / retention / governance 表示の横断 overlay（spec G6: 第 3 branch を作らず 002 内に実装）。Base CR-001-A〜D は 001 へ委譲し、002 は最小実装＋policy/governance 表示を担う。

- [x] T057 Implement NoTrainGuard（opt-in 無しの学習/横断改善/別テナント改善利用を拒否, **capability_allowed**: provider_no_train_required かつ no-train 保証 provider 無し→False で **block**[GQ1], block 時 `temporarily_unavailable`）in `src/raku_rag/manufacturing/governance/no_train.py` (depends T010) — FR-MFG-016/017/018/029, research R9
- [x] T058 Implement RetentionManager（既定 顧客 365 / 監査 365, tenant 上書き[ガイド 30–3650], 失効は 001 tombstone/カスケードへ委譲）in `src/raku_rag/manufacturing/governance/retention.py` (depends T010) — FR-MFG-020, GQ2, research R11
- [x] T059 Implement tamper-evidence（AuditLogEntry の prev_hash/entry_hash hash chain）in `src/raku_rag/manufacturing/domain/audit.py` (depends T009) — FR-MFG-023, Base CR-001-A
- [x] T060 [P] **Governance hard-gate（SC-MFG-009）**: opt-in 無しの学習利用 0, no-train 非保証 capability が block される（temporarily_unavailable・推測なし）in `tests/manufacturing/test_no_train.py`（quickstart S8, FR-MFG-016〜018, GQ1）
- [x] T061 [P] **Audit hard-gate（SC-MFG-010）**: 規定イベント記録率 100%・欠落 0, **PII/secret/機密本文 混入 0（参照IDのみ）**, tenant 越え参照拒否 in `tests/manufacturing/test_audit_coverage.py`（quickstart S9, FR-MFG-021〜023）
- [x] T062 Implement `GET/PUT /v1/manufacturing/policy/data-use`（training_opt_in=true は opt_in_contract_ref 必須, 変更は policy_version 更新＋audit）in `src/raku_rag/manufacturing/api/policy.py` (depends T057, T058) — FR-MFG-018/019
- [x] T063 Implement `GET /v1/manufacturing/governance/status`（no_train/audit_coverage/safety_gate/draft_review/groundedness ＋ ismap_readiness_memo「見据えた設計」）in `src/raku_rag/manufacturing/api/policy.py` (depends T062) — FR-MFG-024/025/026
- [x] T064 Implement `GET /v1/manufacturing/audit/export`(format=jsonl|csv, 参照IDのみ・tenant スコープ限定) + admin no-train/retention/provider setting change の audit 記録 in `src/raku_rag/manufacturing/api/policy.py` (depends T059) — FR-MFG-021/023, Base CR-001-A/C
- [x] T065 Document Base Change Requests CR-001-A〜D（audit 構造化+tamper-evidence / provider no-train capability 検証 / retention・export / platform security NFR）as design memo for 001 integration in `specs/002-manufacturing-field-knowledge-rag/base-cr-notes.md` — FR-MFG-024/025, research R13
- [x] T066 Integration: **PoC v0 vertical slice（FR-MFG-027）** end-to-end（PDF/DOCX/XLSX/CSV 取り込み→メタデータ/import→設備/アラーム/工程/不良/部品検索→根拠付き回答[approved/obsolete/draft 反映・high-risk approved 必須]→DraftArtifact[自動 approved なし]→最小 demo→KPI 計測）in `tests/manufacturing/test_poc_vertical_slice.py`（quickstart S11）

**Checkpoint**: no-train block・audit 網羅・retention・governance 表示が成立、PoC v0 vertical slice が end-to-end で成立

---

## Phase 10: Polish & Cross-Cutting Concerns

- [x] T067 [P] quickstart S1〜S11 検証スクリプト in `tests/manufacturing/test_quickstart.py`
- [x] T068 [P] Documentation（solution-layer architecture, 製造業 parser/メタデータ追加ガイド, safety gate/draft/governance API 使用例, 001 再利用境界）in `docs/manufacturing/`
- [x] T069 [P] Unit tests（HighRiskClassifier カスケード, safety_block_reason 正規化, Countermeasure 2 軸正規化, approval lifecycle, audit redaction）in `tests/manufacturing/unit/`
- [x] T070 Security hardening review（audit に PII/secret/本文非保存, tenant 越え参照, draft 自動確定なし, no-train block, ACL マッピング漏れ）in `tests/manufacturing/test_security_review.py`
- [x] T071 Extend 001 EvaluationRunner with PoC KPI + safety telemetry（baseline relative）と safety hard gate（absolute）の統合 in `src/raku_rag/manufacturing/kpi/poc_metrics.py`（001 eval/runner / Dagster scheduled evaluation run と連携）— FR-MFG-028, SC-MFG-012
- [x] T071a Implement Dagster manufacturing quality checks in `src/raku_rag/dagster/checks/manufacturing.py` — high-risk approved citation requirement satisfied、ACL leakage = 0、tenant isolation leakage = 0、deleted documents not searchable、spreadsheet citation cell_range valid、recall@k / citation accuracy baseline regression
- [x] T072 Minimal PoC Web UI / API demo（質問・回答・引用・文書状態・warning・feedback）in `poc-ui/` — FR-MFG-027

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup(P1)** → **Foundational(P2, 全 US をブロック)** → **User Stories(P3–P8)** → **Governance Overlay(P9)** → **Polish(P10)**
- US1 と US2 は **P1（MVP）**。US1 は seed 済み承認文書で独立テスト可、フルパスは US2 依存
- US3/US4/US6 は **P2**、US5 は **P3**。いずれも Foundational 後に着手可（US 間は独立テスト可能）
- **Governance Overlay(P9)** は AuditLogWriter(T009)/DataUsePolicyStore(T010) に依存し、audit が全 US で蓄積された後に網羅性 hard-gate（T061）と PoC slice（T066）を検証
- 本 layer 全体が **001-rag-platform 実装済み**（tenant/ACL/ingestion/retrieval/answer/groundedness/deletion/eval/cost/visual/13 抽象）を前提とする

### User Story Dependencies

- **US1（P1）**: Foundational 後に着手、他 US 非依存（seed データで独立テスト）
- **US2（P1）**: Foundational 後に着手、US1 と統合してフルパス（独立テスト可能）
- **US3（P2）**: Foundational 後。001 retrieval を再利用、US 間独立
- **US4（P2）**: Foundational 後。SafetyGate(T017) を draft 安全項目に再利用
- **US5（P3）**: Foundational 後。audit(T009) 蓄積に依存（US1〜US4/US6 の audit を集計）
- **US6（P2）**: Foundational 後。T011 ACL マッピングを全エンドポイントへ強制（T053 は各 router 完成後）

### Within Each User Story

Tests 先行(FAIL 確認) → Models/Entities → Services（Classifier/Gate/Enricher/Retriever/Generator）→ Endpoints → Audit 結線。safety/security hard-gate（T014/T015/T039/T047/T052/T060/T061）は baseline 不問で PASS 必須。

### Parallel Opportunities

- **Setup**: T003/T004
- **Foundational**: T008（interfaces）は T005/T006 と並行可。T009/T010/T011 は T006/T005 完了後
- **US1**: T012/T013/T014/T015（テスト）
- **US2**: T022/T023/T024（テスト）, **T025/T026（parser 並列）**
- **US3**: T032/T033（テスト）
- **US4**: T038/T039/T040（テスト）
- **US5**: T046/T047（テスト）
- **Governance**: T060/T061（hard-gate テスト並列）
- **Polish**: T067/T068/T069

---

## Parallel Example: User Story 2（取り込み）

```bash
# テストを並列:
Task: "Integration DOCX/XLSX/CSV ingest in tests/manufacturing/test_ingest_formats.py"      # T022
Task: "Integration cell citation in tests/manufacturing/test_cell_citation.py"               # T023
Task: "Integration approval lifecycle in tests/manufacturing/test_approval_lifecycle.py"     # T024

# parser 実装を並列:
Task: "DocxParser in src/raku_rag/providers/parsers.py"                                       # T025
Task: "SpreadsheetParser (XLSX/CSV cell anchors) in src/raku_rag/providers/parsers.py"        # T026
```

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Setup → Foundational（**ブロッキング**, T009 audit / T010 policy / T011 ACL マッピング基盤）
2. US2（取り込み＋メタデータ/承認）+ US1（安全側回答）→ フルパス
3. **STOP & VALIDATE**: quickstart S1〜S4（取り込み・即答・safety gate・obsolete/draft）, S7（ACL）
4. Deploy/demo（PoC コア）

### Incremental Delivery

US1+US2（MVP）→ US3（類似トラブル）→ US4（ドラフト）→ US6（ACL マッピング）→ US5（ダッシュボード）→ **Governance Overlay**（no-train/audit/retention/PoC slice）。各段で独立テスト＋safety/security hard gate 維持。

### Guardrails（absolute hard gate, 1 件でもマージ不可）

- **SC-MFG-006**（T014）: high-risk × approved 引用欠如での断定 0
- **SC-MFG-007**（T039）: AI 生成物の自動確定 0
- **SC-MFG-008**（T052）: 権限外（工場/部署/役職/設備領域）漏洩 0（001 ACL hard gate 継承）
- **SC-MFG-009**（T060）: opt-in 無し学習利用 0 / no-train 非保証 capability は block
- **SC-MFG-010**（T061）: 規定 audit イベント記録率 100% / PII 混入 0
- **SC-MFG-011**（T015）: obsolete/draft を正式根拠に使用 0
- 001 由来: ACL 漏洩 / 削除再出現 / tenant 分離（001 security スイート継承）

### Baseline Relative Gate（T071）

PoC KPI（FR-MFG-028）＋ safety telemetry（FR-MFG-030）を 001 EvaluationRunner の baseline relative ゲートへ。

---

## Notes

- [P] = 別ファイル・依存なし。[Story] でトレーサビリティ。
- 本 layer は **001 を再定義せず**、`src/raku_rag/manufacturing/` で拡張・上乗せのみ（parser だけ 001 `providers/parsers.py` に追加）。
- safety gate は 001 groundedness gate の**後段 1 段上乗せ**。認可・削除・検索は 001 機構をそのまま強制。
- telemetry/KPI は **audit log を単一真実源**として導出（二重カウントしない）。
- GQ1=block / GQ2=顧客 1 年・監査 1 年（DataUsePolicy 既定）で確定済み。
- Dagster は sync/parse/chunk/embedding/index/eval/KPI materialization の control plane。DraftArtifact/review state machine、request-time authz、audit/ACL source of truth には使わない。
- **Loop / Track-A 整合（`docs/loop-engineering.md` §8, 2026-06-19）**: 絶対ハードゲート=6 本（SC-MFG-006/007/008/009/010/011）、T047/SC-MFG-013 は Tier B。Phase 2 は **stdlib dataclass + in-memory** で実装し、T007（SQLAlchemy/Alembic）と Dagster 系（T011a/T031a/T047a/T051a/T071a）は本番アダプタ track へ延期。ACL/leakage チェックは US1 から Tier A で毎回実行。

## Gap Remediation Backlog — design-vs-implementation audit (2026-06-20)

NOT part of the original T001–T072 (all `[x]`, gate green). These are confirmed gaps found by a
post-implementation design-vs-impl audit (each adversarially re-verified; S1/S2 reproduced in code).
Filed for visibility per request; implementation deferred. `[!]` = safety boundary (human-owned).

### Safety boundary (reproduced) — highest priority
- [ ] GAP-S1 [!safety] high-risk semantic recall is still incomplete for novel phrasings (Rule 2 / FR-MFG-015 / Q3): the original reproduced false-negatives were longer, keyword-free dangerous queries (e.g. "open the inner housing then proceed", "reach into the moving rollers and clear the blockage by hand") that bypassed the approved-citation hard gate (FR-MFG-005/SC-MFG-006). **MITIGATED locally**: `physical_intervention` reason codes (EN+JP) now catch those reproduced physical-intervention patterns; the release-blocking `high_risk_recall_probe` and synthetic corpus cover known dangerous paraphrases plus benign false-positive controls. **WHY STILL OPEN**: the MVP `ExtractiveLLMProvider` has no semantic danger-classification head, and deterministic keyword/rule expansion cannot prove recall for genuinely novel dangerous wording without becoming an all-high-risk classifier. Full closure requires a production danger-classification LLM/guardrail plus SME/red-team corpus expansion and human safety review. Do not mark this `[x]` on local heuristic/corpus expansion alone.
- [x] GAP-S2 [!safety] deleted doc reappears via draft (top risk: deleted-content reappearance): `manufacturing/app.py:730` delete_document tombstones the base store but never clears `_mfg_meta`; `drafts/generator.py:198` reads `_mfg_meta` directly (not via the tombstone-excluding 001 retrieval), so a deleted APPROVED+effective doc can flip a draft safety item to confirmed=True. answer/search/trouble are protected (go through retrieval); only the draft path bypasses. **FIXED 2026-06-20**: `get_mfg_meta` is now tombstone-aware (returns None for a tombstoned doc), so the draft path can't confirm a safety item from deleted approved metadata; a restore (re-ingest) un-tombstones and re-enables it. Verified by tests/manufacturing/test_deletion_draft_evidence.py (positive control + delete + restore). Broader draft-path source ACL/provenance validation remains as GAP-F10/F11.
- [x] GAP-S3 [!safety] poisoned DRAFT becomes primary evidence for a high-risk assertion (Rule 2/3 / FR-MFG-005/006 / SC-MFG-006/011): for a high-risk query where an APPROVED+effective safety doc and a contradicting DRAFT doc both match, `answer` returns `status="ok"` with `citations[0]` = the DRAFT and the asserted `text` is the draft's dangerous content (reproduced 2026-06-20/21 — "skip lockout tagout, remove the guard while running"). The high-risk approved-citation rule fires only when there is NO approved citation; when an approved doc coexists it does not DEMOTE the draft from primary, so a poisoned/unapproved source drives a dangerous high-risk answer. `test_safety_gate.py`'s positive control never pits an approved doc against a competing draft, so this path is unverified (green ≠ correct). **Reproduced by the 011 eval probe** `source_poisoning_probe` (`src/raku_rag/eval/probes.py`, held OUT of the default suite + SECURITY_CHECKS pending this fix; stub-tested in `tests/security/test_eval_security_probes.py`). See `docs/production-readiness/risk-register.md` PR-016. → FIX (human-owned safety path): in the high-risk answer path (`manufacturing/api/answer_ext.py` / `safety/gate.py`) demote draft/obsolete from PRIMARY citation and from asserted text when an approved+effective citation exists (or block if none); add a mechanism-pinned hard-gate test asserting "approved+draft coexist → approved is primary, draft never asserted". THEN add `source_poisoning_probe` to `DEFAULT_PROBES` + `SECURITY_CHECKS` (011) as a release blocker. **FIXED 2026-06-21**: `api/answer_ext.py` demotes any high-risk answer whose PRIMARY citation is not approved+effective → `insufficient_evidence` (`approved_citation_missing`), even when an approved doc is cited elsewhere (no weakening of the existing obsolete-primary demote, groundedness, ACL, deletion, or citation behavior — protected gates `test_safety_gate`/`test_obsolete_draft_evidence`/`test_draft_only` unmodified + green). New hard gate `tests/manufacturing/test_source_poisoning.py` (reproduces the old failure + no-over-block positive control); `source_poisoning_probe` now release-blocking in `DEFAULT_PROBES` + `SECURITY_CHECKS`.

### Functional
- [x] GAP-F01 [func] retention (FR-MFG-020/GQ2): `governance/retention.py` effective_retention / _clamp(30..3650) / expire_document are implemented but UNTESTED, and expire_document has NO caller anywhere (expired data is never actually removed via the tombstone path). → add default/clamp/expiry tests + wire a sweep caller. **FIXED 2026-06-20**: unit tests for default 365/365 + override + clamp(30..3650); `ManufacturingSystem.expire_document` + `run_retention_sweep` (age from 001 Document.created_at vs effective customer-data retention; expires via the 001 tombstone, SC-003) + integration tests. Reuses the delete audit funnel + one `retention.sweep` summary entry (no new uncovered audit category). NOT auto-scheduled (admin/Dagster caller pending).
- [x] GAP-F02 [func] safety-telemetry collection axis (FR-MFG-030/SC-MFG-013): `telemetry/safety_metrics.py:180` collection branch is a no-op but compute() still labels axis=COLLECTION/axis_value=collection_id → tenant-wide high_risk/block counts presented as a single collection's. → real collection filtering (snapshot collection_id on audit entries) or stop labeling axis=COLLECTION; 2-collection test. **FIXED 2026-06-20**: added `AuditLogEntry.collection_id` (additive/default-None), stamped from the answer path, and made `_in_scope` a real filter; per-collection counts now partition the tenant total. Test: test_safety_telemetry.TestTelemetryCollectionAxis.
- [x] GAP-F03 [func] audit coverage under-checks (FR-MFG-021/SC-MFG-010): metadata-update, search query, dashboard access, KPI export, feedback/low-rating are NOT audited; the audit-coverage hard gate (test_audit_coverage.py REQUIRED_EVENT_TYPES) is a closed list of 11 that omits them, so SC-MFG-010 "100%/0 gaps" is FALSELY green. → record those audit actions + extend REQUIRED_EVENT_TYPES. **FIXED 2026-06-20**: added reference-IDs-only audit emissions for `metadata.update`/`search.query`/`dashboard.access`/`kpi.export` + 4 REQUIRED_EVENT_TYPES predicates + e2e driver (PII=0 & tamper-chain still verified). DEFERRED: feedback/low-rating to GAP-F04 (no ingestion path yet) — that 5th category stays uncovered until F4. **→ NOW DONE in GAP-F4 (2026-06-20): the `feedback` predicate + driver landed, so SC-MFG-010 audit coverage is 5/5 (100%).**
- [x] GAP-F04 [func] low-rating surface (FR-MFG-012/028): dashboard.low_rating=() and KPI low_rating_rate=0.0 are hardcoded; feedback never reaches the manufacturing audit/KPI. → wire 001 feedback through the audited answer path + non-zero test. **FIXED 2026-06-20**: `ManufacturingSystem.record_answer_feedback` writes a reference-IDs-only `feedback.low_rating` audit entry (rating 1-5 + low flag in client_metadata; **comment dropped — never persisted**); dashboard `low_rating_answers` + KPI `low_rating_rate` are now DERIVED from the audit log (single source of truth). Also extended `REQUIRED_EVENT_TYPES` with the `feedback` predicate + e2e driver — **completes the GAP-F03 deferral: SC-MFG-010 audit coverage is now 5/5 (100%)**. Tests: test_audit_coverage (PII=0 via comment=SECRET_BODY) + test_dashboard_contract.TestLowRatingFeedback.
- [x] GAP-F05 [func] no /v1/manufacturing/* HTTP API (mfg-openapi "API First"): every 002 endpoint exists only as in-memory Python (ManufacturingSystem); no NestJS controller, no answer-service routing. T024a/T030/T037/T043/T051/T062–T064 are `[x]` but only at the in-memory layer. → add NestJS ManufacturingController + answer-service /internal/manufacturing + e2e; or mark the contract Python-layer-only. **FIXED 2026-06-22:** NestJS `ManufacturingController` now exposes the manufacturing contract facade for answer, sync/status, metadata/approval, trouble-case search, drafts create/get/assign/review, dashboard, safety telemetry, KPI, data-use policy, governance status, and audit export; answer-service now exposes matching `/internal/manufacturing/*` routes over the existing `ManufacturingSystem` methods. `apps/api/test/manufacturing.e2e-spec.ts` pins auth, signed-principal tenant forwarding, non-admin mutation denial for protected mutations, and representative forwarding for all contract route families.
- [x] GAP-F06 [func] approval state machine has no transition guard (data-model §B): `ingestion/approval.py:71` transition() accepts any target; obsolete→approved / approved→draft / draft→approved (skip pending_review) are not prevented (existing tests rely on the permissiveness). → allowed-transition table + illegal-transition tests. **FIXED 2026-06-20** (decision: lightweight forward-only): `_assert_legal_transition` blocks backward / obsolete→approved resurrection; forward skips (draft→approved) + idempotent moves stay legal per the "軽量承認ワークフロー" mandate, and `import_external` (source of truth) bypasses the guard. Zero existing tests broke. Test: test_approval_workflow_unit.TestForwardOnlyTransitionGuard.
- [x] GAP-F07 [func] DraftArtifact state machine has no guard (data-model §F): `drafts/review.py:60` decide() never reads current status → draft→approved (skip in_review) works and terminal approved can be re-opened (reproduced). → guard source status; skip/reopen rejection tests. **FIXED 2026-06-20**: source-status guards (approve/reject require in_review; archive from draft|in_review; terminals never re-open) via new `InvalidTransitionError`; the SC-MFG-007 self-approve PermissionError stays first. Zero existing tests broke. Test: test_draft_only.TestStateMachineOrdering.
- [x] GAP-F08 [func] DataUsePolicy (§G) not persisted: no production table; migration 0006 lacks the §G fields; in-memory only (lost on restart/across instances). → add manufacturing_data_use_policy table + RLS, or document where it persists. **FIXED 2026-06-22:** migration `0010_mfg_data_use_policy.sql` adds `manufacturing_data_use_policies` with tenant RLS; `PostgresDataUsePolicyStore` persists safe defaults, opt-in invariants, retention, export flag, version, and updater fields; production composition wires it with `PostgresManufacturingAuditLogWriter`, and `/v1/manufacturing/policy/data-use` / governance status / audit export reach the durable path. Approval state now writes a jsonb-safe `ManufacturingDocumentMetadata` mapping through reused `Document.metadata`. Remaining PR-004 tail: real Postgres survive-restart coverage and deployed-env verification.
- [x] GAP-F09 [func] superseded_by never written: no workflow transition sets it (approved→superseded→obsolete cannot be produced; only via raw fixture). → add supersede() that sets superseded_by + test. **FIXED 2026-06-20**: `ApprovalWorkflow.supersede(tenant,doc,superseded_by,actor)` + `ManufacturingSystem.supersede_document(...)` drive approved→obsolete (forward, legal under GAP-F6) and stamp superseded_by + obsolete_at, audited as `approval.supersede`. No new `superseded` enum (it's OBSOLETE-with-a-pointer); the superseding doc is NOT auto-approved. Test: test_approval_workflow_unit.TestSupersede.
- [x] GAP-F10 [func] draft source selection ignores tombstones (data-model:86 lists draft source selection as tombstone-subject): DraftService.create does no retrieval/tombstone check (same root as GAP-S2). → validate source_document_ids against the deletion log in DraftService.create. **FIXED 2026-06-20** (with GAP-F11): DraftService gains a `can_use_source` closure that drops any tombstoned source id/citation before generation.
- [x] GAP-F11 [func] draft source selection ignores ACL (SC-MFG-008, data-model:146): DraftService holds no AclPolicy handle; a caller passing an unauthorized doc_id directly to generate_draft embeds it into provenance unchecked; the only test feeds already-ACL-stripped citations. → can_read_document check in the draft path + direct-unauthorized-id leakage test. **FIXED 2026-06-20**: `ManufacturingSystem._can_use_draft_source` reuses self._mvp.registry (tombstone) + self._mvp.acl.can_read_document (deny-by-default) — no parallel authz path; filters context_citations + source_document_ids in DraftService.create (drop, not reject; never-ingested ids kept = no leak/no oracle). Tests: test_acl_mapping (direct-pass blocked / authorized kept / tombstoned excluded).
- Cross-spec functional gaps filed in their own specs: GAP-F12 (006 — marketing contradiction stub), GAP-F13 (010 — regulated policies not applied), GAP-F14 (003/004/005/006 — domain-table RLS untested).

### Minor
- [x] GAP-M01 [minor] FR-MFG-007 on-site-confirmation notice is implemented (answer_ext.py:54 ONSITE_CONFIRMATION_NOTICE, wired onto the answer) but NO test asserts the .notice text — only the boolean requires_onsite_confirmation; a blanked notice stays green. → assert notice text (and None when not high-risk) in test_safety_gate.py. **FIXED 2026-06-20** (test-only): test_safety_gate asserts ans.notice == ONSITE_CONFIRMATION_NOTICE on the high-risk positive control and None on the non-high-risk negative control.
- [x] GAP-M02 [minor] /v1/answer manufacturing fields are flat dataclass attrs, not nested under a `manufacturing:{}` key (mfg-openapi §A) — no JSON/HTTP boundary exists yet (ties to GAP-F05). → nest when the facade/serializer is built. **FIXED 2026-06-22:** `_manufacturing_answer_json()` serializes `high_risk`, `high_risk_reason_codes`, `safety_block_reason`, `obsolete_warning`, `requires_onsite_confirmation`, and `notice` under a nested `manufacturing` object while keeping approval provenance on citations; pinned by `tests/integration/test_manufacturing_answer_endpoint.py` and the NestJS manufacturing e2e facade.
- [x] GAP-M03 [minor] safety-telemetry response omits time_range {from,to,granularity}; the granularity query param is discarded (dashboard.py:130 returns the raw tuple/None). → populate the time_range object + shape test. **FIXED 2026-06-20**: SafetyTelemetryView.time_range is now the `{from,to,granularity}` object (granularity echoed; from/to null when no window). Test: test_dashboard_contract time_range shape tests.
- [x] GAP-M04 [minor] 0006 migration has no enum CHECK...IN constraints; the AI-self-approve DB CHECK (0006:236) is untested (the runtime guard IS tested via test_draft_only.py). → add enum CHECKs + assert the 0006 CHECK in test_manufacturing_migration_sql.py. **FIXED 2026-06-22:** `0006_manufacturing_domain.sql` now pins DB-level CHECK constraints for document kind, approval status/source, countermeasure type/class, draft artifact type/status/creator, classification source, and safety block reason. `tests/contract/test_manufacturing_migration_sql.py` now asserts the enum CHECKs and the AI-generated draft cannot be approved by DB constraint.
