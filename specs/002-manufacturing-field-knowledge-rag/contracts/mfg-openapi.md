# API Contract: Manufacturing Solution Layer

**Feature**: `002-manufacturing-field-knowledge-rag` | **Date**: 2026-06-19 | API First（Principle VII）

本 layer は **001 の `/v1` API を再利用**し（[001 openapi](../001-rag-platform/contracts/openapi.md):
`/v1/search` `/v1/answer` `/v1/ingest` `/v1/admin/*` `/v1/evaluations/*` `/v1/feedback`）、製造業
solution layer 固有のエンドポイントと、既存エンドポイントへの **製造業拡張フィールド**のみを定義する。
認証・エラー・status（`ok|insufficient_evidence|budget_exceeded|temporarily_unavailable`）・追跡
識別子・`correlation_id` は 001 を継承。

> 凡例: 【拡張】= 001 既存エンドポイントへのフィールド追加。【新規】= 002 solution layer の追加。

---

## A. Answer / Search への製造業拡張【拡張】

### POST /v1/answer（high-risk safety gate 上乗せ, FR-MFG-005/006/007/015）

- req 追加: `{ ..., manufacturing_filters?: { equipment_id?, process_id?, alarm_code?, defect_type?,
  part_no?, customer?, document_type? }, intent_hint? }`
- res 200 追加フィールド（001 answer に上乗せ）:
  ```json
  {
    "status": "ok | insufficient_evidence",
    "answer": "...",
    "citations": [{ "...001 fields...", "approval_status": "approved",
                    "effective_date": "2026-01-10", "approval_source": "imported" }],
    "manufacturing": {
      "high_risk": true,
      "high_risk_reason_codes": ["disassembly", "safety_device"],
      "safety_block_reason": null,
      "obsolete_warning": false,
      "requires_onsite_confirmation": true,
      "notice": "作業実施前に現場責任者または有資格者の確認が必要です。"
    },
    "correlation_id": "trace_..."
  }
  ```
- high-risk × approved 引用欠如 → `status:"insufficient_evidence"`,
  `manufacturing.safety_block_reason:"approved_citation_missing"`（断定しない, FR-MFG-005, SC-MFG-006）。
- obsolete 文書参照時 → `obsolete_warning:true`＋警告表示（FR-MFG-006, SC-MFG-011）。
- citation には `approval_status` / `effective_date` / `approval_source` を必須付与（FR-MFG-004, Q1）。

### POST /v1/search【拡張】

- req 追加: `{ ..., manufacturing_filters?: {...同上...} }`（001 metadata filter を製造業タグへ写像）
- res の各 result に `approval_status` / `effective_date` を付与（latest_approved/obsolete/有効日の識別,
  US2-2）。XLSX/CSV 由来は引用範囲としてセル座標（`sheet`, `row`, `col`）を返す（FR-MFG-002）。

---

## B. Ingestion + 製造業メタデータ / 承認【拡張 + 新規】

### POST /v1/ingest【拡張】（DOCX/XLSX/CSV ＋ 製造業メタデータ, FR-MFG-001/003）

- req 追加: 受理フォーマットに DOCX/XLSX/CSV を追加（PDF/画像/スキャンは 001 visual RAG 再利用）。
  `{ ..., manufacturing_metadata?: { equipment_id?, process_id?, alarm_code?, defect_type?, part_no?,
  customer?, document_type?, safety_category?, quality_category?, equipment_operation_category?,
  hazard_tags?: [...] }, approval?: { approval_status?, effective_date?, approval_source?: "imported"|
  "workflow", approved_by?, approved_at?, superseded_by? } }`
- res 202: `{ job_id?, ingestion_run_id, status_url }`（001 非同期 ingestion を再利用。AWS MVP は SQS + Python worker、Dagster は optional control plane 互換）。

### POST /v1/manufacturing/sources/{source_id}/sync【新規/001 委譲】

manual sync request。NestJS API は PostgreSQL に `IngestionRun(status=queued, trigger=manual)` を作成し、AWS MVP では SQS に sync job を enqueue する。Dagster が有効な環境では `ingestion_job sensor` が同じ queued run を観測できる。製造業 metadata enrichment は SQS worker の enrichment step または Dagster asset `manufacturing_metadata_enriched_elements` として実行される。
- req: `{ collection_id?, manufacturing_filters?, force?: bool }`
- res 202: `{ ingestion_run_id, status:"queued", status_url:"/v1/manufacturing/ingestion-runs/{ingestion_run_id}" }`

### GET /v1/manufacturing/sources/{source_id}/sync-status【新規/001 委譲】

SourceSyncState と最新 run summary に、製造業 metadata/approval 差分の要約を加えて返す。
- res 200: `{ source_id, collection_id, status, last_observed_at?, last_successful_sync_at?,
  last_ingestion_run_id?, observed_count, changed_count, deleted_count, metadata_only_changed_count,
  approval_metadata_changed_count, failed_count, freshness, last_error?, dagster_run_id?, dagster_run_url? }`
- `dagster_run_id` / `dagster_run_url` は内部運用者向け。end user に Dagster UI を直接見せない。

### GET /v1/manufacturing/ingestion-runs/{ingestion_run_id}【新規/001 委譲】

IngestionRun の詳細と DocumentProcessingState summary。
- res 200: `{ ingestion_run_id, type, trigger, status, source_id?, collection_id?, started_at?, finished_at?,
  summary:{ observed_count, changed_count, deleted_count, skipped_count, metadata_only_changed_count,
    approval_metadata_changed_count, failed_count },
  documents:[{ document_id, source_document_id, parse_status, chunk_status, embedding_status, index_status,
    approval_status?, last_indexed_at?, last_error? }],
  dagster_run_id?, dagster_run_url?, correlation_id }`

### PUT /v1/manufacturing/documents/{document_id}/metadata【新規】

- 製造業メタデータ・承認メタデータの設定/更新（FR-MFG-003/004）。変更は audit 対象（FR-MFG-021）。
- res 200: `{ document_id, manufacturing_metadata, approval }`。

### POST /v1/manufacturing/documents/{document_id}/approval【新規】（FR-MFG-004/004a）

- req: `{ to_status: "pending_review"|"approved"|"obsolete", actor }`、または
  `{ import_external: { approval_status, effective_date, approved_by, approval_source: "imported" } }`。
- imported は source of truth として優先。res 200: `{ document_id, approval_state }`（audit 記録）。

---

## C. 類似トラブル事例【新規】（FR-MFG-008/009）

### POST /v1/manufacturing/trouble-cases/search

- req: `{ symptom_query, manufacturing_filters?, top_k? }`
- res 200:
  ```json
  {
    "status": "ok",
    "results": [{
      "trouble_case_id": "tc_12",
      "symptom": "振動増加＋異音",
      "equipment_id": "eq_3", "process_id": "pr_1",
      "failure_mode": { "name": "軸受摩耗", "description": "..." },
      "countermeasures": {
        "provisional": [{ "measure_id": "m1", "description": "...", "type": "candidate",
                          "measure_class": "provisional", "label": "過去事例に基づく候補・参考" }],
        "permanent":  [{ "measure_id": "m2", "description": "...", "type": "candidate",
                          "measure_class": "permanent",  "label": "過去事例に基づく候補・参考" }]
      },
      "recurrence_prevention": "...",
      "citations": [{ "...001 citation fields...", "approval_status": "approved" }]
    }],
    "correlation_id": "trace_..."
  }
  ```
- 暫定/恒久を分離（G4）。permanent でも `label` で候補・参考に正規化（Hard Rule 4, FR-MFG-009）。
- ACL 権限外の事例は結果に出さない（001 pre-filter, SC-MFG-008）。

---

## D. ドラフト生成・レビュー【新規】（FR-MFG-010/010a/010b, G1）

### POST /v1/manufacturing/drafts

- req: `{ kind: "checklist"|"trouble_report"|"quality_report"|"training"|"faq", context: {...},
  template_id?, manufacturing_filters? }`
- res 200: 必ず `status:"draft"`:
  ```json
  {
    "artifact_id": "art_9",
    "type": "faq",
    "status": "draft",
    "created_by": "ai",
    "source_citations": [{ "...001 citation..." }],
    "source_document_ids": ["doc_1", "doc_2"],
    "template_id": "tpl_faq_v1",
    "audit_log_ref": "log_...",
    "notice": "本ドラフトはレビュー必須です。reviewer の approve まで正式公開物ではありません。",
    "correlation_id": "trace_..."
  }
  ```
- AI は自動 approved にしない（Hard Rule 1, SC-MFG-007）。安全項目は approved 根拠が無ければ断定しない。

### POST /v1/manufacturing/drafts/{artifact_id}/assign

- req: `{ reviewer_id? | reviewer_group?, reviewer_role? }` → `status:"in_review"`、audit 記録。

### POST /v1/manufacturing/drafts/{artifact_id}/review

- req: `{ reviewer, decision: "approved"|"rejected"|"archived", comment? }`
- res 200: `{ artifact_id, status, reviewer_id, reviewed_at, approval_decision, review_comment }`。
  approved は reviewer 判断のみ（多段承認・電子署名なし）。全 transition は audit（FR-MFG-021）。

### GET /v1/manufacturing/drafts/{artifact_id}

- res 200: DraftArtifact 全体（audit trail: 生成時刻/生成者/テンプレート/使用文書一覧, FR-MFG-010b）。

---

## E. ナレッジ運用 Dashboard / Safety Telemetry / KPI【新規】（FR-MFG-012/028/030, US5, G2/G3）

### GET /v1/manufacturing/dashboard

- query: `?collection_id=&factory_id=&department_id=&from=&to=`
- res 200: `{ unanswered_question_count, low_rating_answers, frequent_questions,
  frequently_referenced_documents, obsolete_document_candidates, knowledge_gap_areas,
  correlation_id }`（FR-MFG-012, US5-1; 001 feedback/observability 集計）。

### GET /v1/manufacturing/safety-telemetry（FR-MFG-030, US5-2, SC-MFG-013）

- query: `?collection_id=&factory_id=&department_id=&from=&to=&granularity=hourly|daily|custom`
- res 200:
  ```json
  {
    "high_risk_query_count": 128,
    "safety_gate_block_count": 17,
    "safety_gate_block_breakdown": {
      "approved_citation_missing": 11,
      "insufficient_evidence": 4,
      "other_block": 2
    },
    "axis": { "tenant_id": "t1", "factory_id": "f1", "department_id": "d2" },
    "time_range": { "from": "...", "to": "...", "granularity": "daily" },
    "source": "audit_log",
    "correlation_id": "trace_..."
  }
  ```
- audit log を単一真実源として導出（二重カウントなし, FR-MFG-030）。内訳は相互排他。

### GET /v1/manufacturing/kpi（FR-MFG-028, SC-MFG-012）

- query: `?collection_id=&from=&to=&format=json|csv`
- res 200: `{ self_resolution_rate, average_time_to_answer:{p50,p95}, grounded_answer_rate,
  insufficient_evidence_rate, low_rating_rate, unanswered_question_count,
  frequently_referenced_documents, obsolete_document_candidates, expert_interruption_reduction,
  high_risk_query_count, safety_gate_block_count, materialized_at, source_ingestion_run_id? }`。export 可（001 evaluation/metrics と
  Dagster `manufacturing_dashboard_metrics` を再利用）。

---

## F. Governance: DataUsePolicy / No-train【新規】（FR-MFG-016〜020/029, GQ1/GQ2）

### GET /v1/manufacturing/policy/data-use

- res 200: `{ tenant_id, no_train_default: true, training_opt_in: false, provider_no_train_required:
  true, no_train_fallback: "block", retention_period_customer_days: 365,
  retention_period_audit_days: 365, export_enabled, policy_version }`（営業/管理/監査で説明可能）。

### PUT /v1/manufacturing/policy/data-use（admin）

- req: `{ training_opt_in?, opt_in_contract_ref?, retention_period_customer_days?,
  retention_period_audit_days?, export_enabled?, provider_no_train_required? }`
- `training_opt_in=true` は `opt_in_contract_ref` 必須（FR-MFG-018）。変更は audit＋`policy_version`
  更新（FR-MFG-019）。retention は tenant 上書き（既定 365, ガイド 30–3650; GQ2）。

### GET /v1/manufacturing/governance/status（FR-MFG-024, AI ガバナンス説明）

- res 200: `{ no_train: {...}, audit_coverage: {...}, safety_gate: {...}, draft_review: {...},
  groundedness: {...}, ismap_readiness_memo: "見据えた設計（取得・完全準拠は MVP 非ゴール）" }`
  （FR-MFG-024〜026; high-risk/safety gate/draft review/no-train/audit/groundedness を中核機能として提示）。

> capability に no-train 保証 provider が無い場合、当該機能は `temporarily_unavailable`（block, GQ1）。
> `provider config / no-train 検証`自体は 001 側（Base CR-001-B）。

---

## G. Audit Export【新規/委譲】（FR-MFG-021〜023, Base CR-001-A/C）

### GET /v1/manufacturing/audit/export（admin）

- query: `?from=&to=&format=jsonl|csv`
- res 200: 構造化 AuditLogEntry の export（参照IDのみ・PII/secret 非含有, SC-MFG-010）。tenant スコープ
  限定・tenant 越え参照不可。tamper-evidence（hash chain）・export/retention の基盤実装は Base CR-001-A/C
  へ委譲、002 はエンドポイント契約と最小記録を担う。

---

## Versioning

- 001 と同じく `/v1` 配下。製造業エンドポイントは `/v1/manufacturing/*` 名前空間に分離し、001 既存
  契約を壊さない。後方非互換変更は `/v2` を追加し旧版契約を維持（001 FR-020 継承）。
- 製造業拡張フィールドは 001 既存レスポンスへ **加算のみ**（既存フィールドの意味を変えない）。

---

## 安全・監査の API レベル不変条件（hard）

- high-risk × approved 引用欠如 → 断定回答を**返さない**（`insufficient_evidence`+
  `safety_block_reason`, SC-MFG-006）。
- AI 生成物は API 上 **常に `status:"draft"`** で返り、自動 approved にならない（SC-MFG-007）。
- obsolete/draft を正式根拠に使わない・obsolete は warning（SC-MFG-011）。
- 権限外（工場/部署/役職/設備領域）の文書・事例・引用を返さない（001 ACL pre-filter, SC-MFG-008）。
- safety-telemetry / kpi / audit-export は audit log を単一真実源とし、PII/secret を露出しない
  （SC-MFG-010/013）。
