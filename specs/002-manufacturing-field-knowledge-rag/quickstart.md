# Quickstart & Validation Guide: Manufacturing Field Knowledge RAG (Solution Layer)

**Feature**: `002-manufacturing-field-knowledge-rag` | **Date**: 2026-06-19

本ガイドは PoC v0 vertical slice（FR-MFG-027）と製造業 solution layer の end-to-end 検証シナリオを
示す。実装詳細・コードは含まず `tasks.md` と実装フェーズに委ねる。基盤の検証は
[001 quickstart](../001-rag-platform/quickstart.md) を継承し、本ガイドは **002 固有の安全/承認/
draft/governance** の受け入れ基準のみを扱う。詳細は [data-model.md](./data-model.md) /
[contracts/](./contracts/) を参照。

## Prerequisites

- 001-rag-platform が起動可能であること（Python 3.12 / Postgres+pgvector / MinIO / Redis）。
  001 quickstart の Prerequisites を満たす。
- LLM/Embedding provider（high-risk LLM 分類・draft 生成・回答に使用）の資格情報。**no-train 保証**の
  ある provider を用いる（無い capability は block されるため, GQ1）。
- サンプル製造業文書一式:
  - 承認済み設備マニュアル（DOCX, approved＋effective_date）
  - 設備台帳/点検表（XLSX/CSV; セル引用の検証用）
  - 図面 PDF・スキャン点検表（画像; 001 visual RAG 経由）
  - 過去トラブル報告（DOCX/PDF; TroubleCase/FailureMode/Countermeasure を含む）
  - **obsolete 文書**と **draft 文書**（安全側挙動の検証用）
  - 安全文書が存在しない危険作業クエリ用のギャップ（意図的に承認文書を用意しない）
- 環境変数: 001 と同一（`DATABASE_URL` / `S3_*` / `REDIS_URL` / `<PROVIDER>_API_KEY` /
  `TOKEN_SIGNING_PUBLIC_KEY`）。

## Setup（概念手順）

1. 001 のインフラ・API・worker を起動（001 quickstart Setup 1–4）。
2. 製造業 solution layer のマイグレーション適用（Factory/Equipment/TroubleCase/DraftArtifact/
   DataUsePolicy/AuditLogEntry の metadata テーブル）。
3. tenant の `DataUsePolicy` を seed（既定: `no_train_default=true`, `training_opt_in=false`,
   `provider_no_train_required=true`, `no_train_fallback=block`, retention 顧客 365 / 監査 365）。
4. Factory/ProductionLine/Process/Equipment と ACL（部署=group/role, 工場=Factory, 役職=role,
   設備領域=Process/Equipment）を seed。

## Validation Scenarios（受け入れ基準に対応）

### S1. 製造業文書の取り込み＋メタデータ＋承認（US2 / FR-MFG-001/002/003/004）
1. DOCX/XLSX/CSV を `POST /v1/ingest`（`manufacturing_metadata` ＋ `approval` 付き）。`job_id` 取得。
2. `GET /v1/admin/jobs` で `succeeded` を確認（001 ingestion 再利用）。
3. `POST /v1/search` に `manufacturing_filters`（equipment_id / alarm_code 等）。
   - **期待**: 製造業メタデータでフィルタでき、結果に `approval_status`/`effective_date`。
   - XLSX/CSV 由来の引用は `sheet`/`row`/`col` のセル座標で返る（FR-MFG-002）。

### S2. 根拠付き即答（US1 / FR-MFG-005, [base:FR-012/013/014]）
1. 承認済みマニュアルに答えのある質問（例「アラーム E-152 の対処は？」）を `POST /v1/answer`。
   - **期待**: `status:"ok"`、citation に document/chunk＋`approval_status:"approved"`/`effective_date`、
     `used_chunks` 付き（US1-1）。

### S3. High-risk safety gate — approved 引用必須（US1 / FR-MFG-005/007/015, **SC-MFG-006 hard gate**）
1. 危険作業（設備停止/分解/感電/高温/高圧/薬品）で、**承認済み安全文書の根拠が無い**質問を
   `POST /v1/answer`。
   - **期待**: 断定せず `status:"insufficient_evidence"`、
     `manufacturing.safety_block_reason:"approved_citation_missing"`、推測手順を返さない（US1-2）。
2. 安全に関わるが曖昧なクエリ → `manufacturing.high_risk:true`（迷えば high-risk, fail-safe）。
3. high-risk で approved 根拠がある場合 → `status:"ok"`＋`requires_onsite_confirmation:true` と
   「作業前に現場責任者/有資格者の確認が必要」表示（FR-MFG-007）。

### S4. obsolete / draft の扱い（FR-MFG-006, **SC-MFG-011 hard gate**）
1. 根拠が **obsolete 文書にしか無い**質問 → 一次根拠にせず、`obsolete_warning:true`、または
   `insufficient_evidence`（US1-3）。
2. 根拠が **draft 文書のみ** → 正式根拠にしない（policy 許可時のみ参考表示）。

### S5. 類似トラブル事例（US3 / FR-MFG-008/009, G4）
1. 症状クエリ（例「振動増加＋異音」）を `POST /v1/manufacturing/trouble-cases/search`。
   - **期待**: 類似 TroubleCase が原因(FailureMode)・対策(Countermeasure)・再発防止・引用つきで一覧化。
   - 対策は **暫定(provisional)/恒久(permanent)に分けて**返る（US3-1）。
   - `measure_class=permanent` でも `label:"過去事例に基づく候補・参考"` で正式手順として断定しない
     （US3-2, Hard Rule 4）。

### S6. ドラフト生成（US4 / FR-MFG-010/010a/010b, **SC-MFG-007 hard gate**, G1）
1. `POST /v1/manufacturing/drafts`（kind=checklist）。
   - **期待**: `status:"draft"`、`source_citations` 付き、レビュー必須 notice（US4-1）。
2. kind=trouble_report → 事実は引用に基づき、未確定事項を draft 上で明示（US4-2）。
3. kind=faq → `status:"draft"`＋`source_citations`/`source_document_ids`、**自動 approved にならない**、
   reviewer approve まで正式公開物にしない（US4-3, G1）。
4. `POST /v1/manufacturing/drafts/{id}/assign` → `in_review`、`.../review`（approved）→ reviewer の
   明示判断のみで確定。全 transition が audit に記録される（FR-MFG-010b）。
5. **負例**: `created_by=ai` の生成物を自動 approved にしようとして拒否される（SC-MFG-007 = 0）。

### S7. ACL マッピング（US6 / FR-MFG-013, **SC-MFG-008 hard gate**, 001 ACL 再利用）
1. 工場A保全（部署=group, 工場=Factory, 役職=role, 設備領域=Process/Equipment）の principal で、
   工場B品質の文書/顧客名/不良/図面を検索・回答・類似事例で参照しようとする。
   - **期待**: 権限外文書・事例・引用が結果に一切出ない（001 FR-022 再利用, US6-1）。

### S8. No-train / Governance（FR-MFG-016〜020/029, **SC-MFG-009 hard gate**, GQ1）
1. `GET /v1/manufacturing/policy/data-use` → `no_train_default:true`, `training_opt_in:false`,
   `no_train_fallback:"block"`, retention 365/365 を確認。
2. opt-in 無しで顧客データを学習・評価改善に使う経路が拒否される（SC-MFG-009 = 0）。
3. **no-train 非保証 provider しか無い capability** を使う操作 → `temporarily_unavailable`（block,
   推測回答しない, GQ1）。
4. `PUT .../policy/data-use` で `training_opt_in=true` を `opt_in_contract_ref` 無しに設定 → 拒否
   （FR-MFG-018）。変更時 `policy_version` 更新＋audit 記録。

### S9. Audit coverage（FR-MFG-021〜023, **SC-MFG-010 hard gate**）
1. S1–S8 の操作後、`GET /v1/manufacturing/audit/export` で規定イベントを確認。
   - **期待**: ingest/metadata/approval transition/draft 生成・review/high-risk 判定/safety gate/answer/
     citation/ACL denial/no-train・retention 設定変更/deletion が **欠落なく（記録率 100%）**記録。
   - 各エントリは参照ID（document_id/chunk_id/citation_id/artifact_id）で追跡され、**PII/secret/
     機密本文が混入しない（0 件）**。tenant 越え参照が拒否される。

### S10. Safety Telemetry / PoC KPI（US5 / FR-MFG-012/028/030, **SC-MFG-013**, G2/G3）
1. `GET /v1/manufacturing/safety-telemetry?factory_id=&department_id=&granularity=daily`。
   - **期待**: `high_risk_query_count` と `safety_gate_block_count`、内訳
     （`approved_citation_missing`/`insufficient_evidence`/`other_block`）が **相互排他**に集計され、
     `source:"audit_log"`（audit を単一真実源, 二重カウントなし, US5-2）。
2. `GET /v1/manufacturing/dashboard` → 未回答/低評価/頻出質問/頻出文書/obsolete候補/ナレッジ不足
   （US5-1）。
3. `GET /v1/manufacturing/kpi?format=csv` → FR-MFG-028 の全 KPI を計測・export（SC-MFG-012）。

### S11. PoC v0 vertical slice 統合（FR-MFG-027）
1. PDF/DOCX/XLSX/CSV 取り込み → 製造業メタデータ付与/import → 設備名/アラームコード/工程名/不良種別/
   部品番号で検索 → 根拠付き回答（approved/obsolete/draft の扱い反映、high-risk は approved 引用必須）→
   DraftArtifact 生成（自動 approved なし）→ 最小 Web UI / API demo で「質問・回答・引用・文書状態・
   warning・feedback」を確認 → PoC KPI を計測。
   - **期待**: 上記 S1–S10 の不変条件を保ったまま一連が成立する。

## Done（MVP / PoC v0 検証完了条件）

- S1–S2（取り込み・即答）が成立し、引用に承認状態が反映される。
- **Safety hard gate**: S3（approved 引用欠如で断定しない, SC-MFG-006）、S4（obsolete/draft を正式
  根拠にしない, SC-MFG-011）、S6（draft 以外で自動確定なし, SC-MFG-007）、S7（権限外漏洩 0,
  SC-MFG-008）、S8（opt-in 無し学習 0・no-train block, SC-MFG-009）、S9（audit 記録率 100%・PII 混入 0,
  SC-MFG-010）がすべて期待通り。
- S5（暫定/恒久分離・候補表示）、S10（safety telemetry 内訳・KPI export, SC-MFG-013/012）が成立。
- S11 で PoC v0 vertical slice が end-to-end で成立。
- 001 由来の ACL 漏洩 / 削除再出現 / tenant 分離の hard gate（001 quickstart S3–S5）を継承して維持。
