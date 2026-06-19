# Phase 0 Research: Manufacturing Field Knowledge RAG (Solution Layer)

**Feature**: `002-manufacturing-field-knowledge-rag` | **Date**: 2026-06-19 |
**Source**: [spec.md](./spec.md), [plan.md](./plan.md)

本 layer は 001-rag-platform を基盤に再利用するため、基盤の技術選択（NestJS API / SQS worker / pgvector / OpenTelemetry / provider 抽象 / optional Dagster control plane）は [001 research](../001-rag-platform/research.md) を継承する。
本ファイルは **002 solution layer 固有の判断**と **spec の clarification（GQ1/GQ2）確定**を記録する。

各項目: Decision / Rationale / Alternatives considered。

---

## R1. DOCX / XLSX / CSV parser の実装方式（FR-MFG-001/002）

- **Decision**: 001 の `Parser` 抽象（`supports(content_type)` / `parse(raw, content_type)`）に
  3 つの parser を追加実装する。DOCX=`python-docx`、XLSX=`openpyxl`、CSV=stdlib `csv`。XLSX/CSV は
  行/列/シート構造を保持し、**セル座標を引用範囲**として表現するため、正規化テキストに
  `sheet!R{row}C{col}` 形式のアンカーを埋め込み、001 の offset_mapping をセル単位に拡張する。
- **Rationale**: 001 は parser 差し替え可能性（Principle IV）を構造的に持つため、上位コード
  （ingestion/retrieval/answer）を変更せずに形式を追加できる。表構造の引用は [base:FR-013]
  offset/citation を表へ拡張する FR-MFG-002 の要求であり、セルアンカー方式で 001 Citation の
  `text_range` を表座標へ写像できる。
- **Alternatives considered**:
  - 全形式を PDF 変換してから 001 既存 PDF parser に流す → セル単位引用が失われ FR-MFG-002 不成立。却下。
  - 専用の表ベクトル store を新設 → 001 VectorStore 抽象の再利用を壊し Principle IV に反する。却下。

---

## R2. High-risk query 判定アーキテクチャ（FR-MFG-015, Q3=C）

- **Decision**: `HighRiskClassifier` を **3 段カスケード**で実装する: (1) 文書/メタデータ分類タグ
  （`document_type`/`safety_category`/`quality_category`/`equipment_operation_category`/
  `hazard_tags`/`process_id`/`equipment_id`）による判定、(2) クエリ意図のルール＋キーワード判定
  （設備停止/分解/感電/高温/高圧/薬品/重量物/安全装置/品質判定/出荷可否/顧客影響/是正処置）、
  (3) 上記で曖昧な場合のみ 001 `LLMProvider` 抽象による意図分類。**いずれか 1 つでも該当すれば
  high-risk**（OR 判定）。判定不能・曖昧は **high-risk に倒す（fail-safe default）**。出力は
  `(is_high_risk: bool, reason_codes: list[str], classification_source: rule|keyword|llm|metadata)`。
- **Rationale**: spec Q3 が metadata＋ルール＋キーワード＋LLM の組み合わせを要求。ルール／キーワード
  先行＋曖昧時のみ LLM で、レイテンシ（answer p95 baseline）とコストを抑えつつ「迷えば high-risk」を
  満たす。判定結果は audit log に `high_risk_classification_result` として記録（FR-MFG-022）し、
  telemetry の単一真実源（FR-MFG-030）と整合。
- **Alternatives considered**:
  - LLM 単独分類 → コスト・レイテンシ増、決定性低下、監査再現性低下。却下（曖昧時のみ補助に格下げ）。
  - metadata のみ → 自由文クエリの危険意図（「分解して点検したい」等）を取りこぼす。却下。

---

## R3. Safety gate と 001 groundedness gate の関係（FR-MFG-005/006/007）

- **Decision**: 安全機構を**新設せず**、001 の 2 段階 groundedness gate（pre-gate / post-generation
  evidence check）の**後段に SafetyGate を 1 段上乗せ**する。SafetyGate は high-risk 判定が真のとき
  に: (a) 使用候補引用に **`approval_status=approved` かつ `effective_date` 有効**な文書が無ければ
  断定を止め `insufficient_evidence`（safety 由来）に倒す、(b) obsolete 文書参照時は **obsolete
  warning を必須付与**、(c) 危険作業には「作業前に現場責任者/有資格者の確認が必要」を表示、(d)
  ブロック時の `safety_block_reason` を **相互排他 1 コード**に正規化（approved_citation_missing →
  insufficient_evidence → other_block の優先順）。
- **Rationale**: 001 gate を弱めず安全側にのみ強化する最小設計。`safety_block_reason` の state
  machine 正規化により FR-MFG-030 の「1 ブロック＝主因 1 コード」「二重カウントしない」を満たす。
- **Alternatives considered**:
  - 001 groundedness gate を改造して安全条件を混ぜる → 基盤を再定義することになり spec の
    「再定義しない」方針・Principle IV に反する。却下（上乗せ層に分離）。
  - 断定停止を approved_citation_missing と insufficient_evidence の両方でカウント → 二重計上で
    telemetry が歪む。却下（優先順 1 コードに正規化）。

---

## R4. 承認ライフサイクル（FR-MFG-004/004a, Q1=Custom-C）

- **Decision**: `approval_status`（draft→pending_review→approved→obsolete）を本 layer の軽量承認
  ワークフローとして保持し、取り込み元（QMS/DMS/SharePoint/Box/PLM）が承認状態を持つ場合は
  `approval_source=imported` として **取り込み値を source of truth** にする。外部承認が無ければ
  `approval_source=workflow` で本 layer が補完。`effective_date`/`approved_by`/`approved_at`/
  `obsolete_at`/`superseded_by` を ManufacturingDocumentMetadata に保持し、001 `Document.metadata`
  へ格納。状態遷移は audit log 対象（FR-MFG-021）。
- **Rationale**: フル DMS を作らずに安全/承認ポリシー（FR-MFG-005）を成立させる最小単位。imported を
  優先することで既存の社内承認資産を二重管理しない。
- **Alternatives considered**:
  - フル DMS / 多段承認経路 / 電子署名を内製 → spec 非ゴール・Hard Rule 6 に反する。却下。
  - 承認状態を持たず「最新＝有効」とみなす → high-risk の approved 引用必須（FR-MFG-005）が成立
    しない。却下。

---

## R5. 製造業エンティティの永続化方式

- **Decision**: 製造業ドメインエンティティ（Factory/Line/Process/Equipment/AlarmCode/Part/Product/
  Customer/DefectType/FailureMode/TroubleCase/Countermeasure/WorkInstruction/InspectionChecklist/
  QualityIssue/TrainingMaterial）は **本 layer の metadata テーブル**として 001 と同じ PostgreSQL に
  追加し、全行 `tenant_id` 必須・001 ACL/tombstone に従属させる。検索対象の本文（マニュアル/標準書/
  トラブル報告）は 001 の Document/Chunk に取り込み、製造業メタデータ（equipment_id/process_id/
  alarm_code/defect_type/part_no/customer 等）は `Document.metadata`/`Chunk.metadata`(JSON) に格納
  して 001 metadata filter（FR-010）で検索する。エンティティは検索結果・引用を製造業文脈へ
  リンクする参照層。
- **Rationale**: 検索/ACL/削除は 001 の Document/Chunk 機構をそのまま使い、製造業エンティティは
  「メタデータの正規化＋関係」を担う薄い層に留める。これにより ACL 漏洩・削除再出現の hard gate を
  001 のまま継承できる（新規検索/認可機構を作らない）。
- **Alternatives considered**:
  - 製造業エンティティごとに独自検索インデックスを持つ → 001 の pre-filter/tombstone を二重化し
    漏洩リスク増。却下。
  - 全てを JSON metadata のみで表現しエンティティ化しない → 類似トラブル一覧（FR-MFG-008）の
    FailureMode/Countermeasure 関係表現が困難。却下（関係が必要な範囲のみエンティティ化）。

---

## R6. 類似トラブル事例検索（FR-MFG-008/009, G4）

- **Decision**: 症状クエリは 001 retrieval（ベクトル検索＋ACL pre-filter）で TroubleCase 由来の
  Chunk を取得し、Chunk metadata 経由で TroubleCase エンティティへ解決、関連 FailureMode（原因）・
  Countermeasure（対策）・再発防止策を一覧化する。Countermeasure は **2 軸**を保持: `type`
  （reference|candidate, 表示/evidence 区分）と `measure_class`（provisional|permanent|unknown,
  性質区分）。表示は **暫定/恒久を分離**し、`measure_class=permanent` でも過去事例由来は
  「過去事例に基づく候補・参考」に正規化して断定しない。
- **Rationale**: 001 検索を再利用しつつ G4（暫定/恒久分離）と Hard Rule 4（過去対策は候補表示）を
  両立。type と measure_class を分離することで「表示の安全側倒し」と「対策の性質情報」を混同しない。
- **Alternatives considered**:
  - 対策を単一 `type` で表現 → 暫定/恒久の性質と参考/候補の表示区分が混ざり G4 不成立。却下。
  - 過去 permanent 対策を正式手順として提示 → Hard Rule 4 違反。却下（候補に正規化）。

---

## R7. DraftArtifact 生成とレビュー導線（FR-MFG-010/010a/010b, Q2=B, G1）

- **Decision**: `DraftGenerator` は checklist/trouble_report/quality_report/training/**faq** を生成し
  **必ず `status=draft`**・`source_citations`/`source_document_ids`/`template_id`/`created_by`/
  `audit_log_ref` を付与する（AI は自動 approved にしない）。`ReviewWorkflow` が状態遷移
  `draft → in_review → approved/rejected/archived` と `reviewer_id`/`reviewer_role`/`assigned_at`/
  `reviewed_at`/`review_comment`/`approval_decision` を管理する（単一 reviewer or reviewer group の
  軽量レビュー、多段承認・電子署名なし）。レビュー済みでも生成根拠・引用・生成時刻・生成者・
  テンプレート・使用文書一覧を audit trail で追跡。
- **Rationale**: Hard Rule 1（AI 生成物自動確定禁止）と SC-MFG-007（draft 以外自動確定 0）を構造で
  保証。FAQ も他 draft と同列に扱い（G1）、自動公開を防ぐ。
- **Alternatives considered**:
  - 生成時に信頼度が高ければ自動 approved → Hard Rule 1 違反。却下（必ず人間 reviewer）。
  - 多段承認・電子署名フロー → 非ゴール・複雑性増。却下（軽量レビュー）。

---

## R8. 部署/工場/役職/設備領域の ACL マッピング（FR-MFG-013）

- **Decision**: **新規認可機構を作らず** 001 ACL（ACLGrant: scope×subject、deny-by-default、
  pre-filter）へマッピングする。**部署＝base ACL group/role**（新規エンティティを作らない）、
  **工場＝Factory エンティティ**、**役職＝role**、**設備領域＝Process/Equipment メタデータ**。
  集計用に AuditLogEntry へ actor 組織コンテキスト `factory_id`/`department_id` を保持し、safety
  telemetry の集計軸（factory/department）に使う（FR-MFG-030）。
- **Rationale**: 001 の ACL hard gate（SC-004）を継承し、SC-MFG-008（権限外漏洩 0）を 001 のまま
  満たす。department をエンティティ化しないことで認可面の二重定義を避ける。
- **Alternatives considered**:
  - 製造業専用の RBAC を新設 → 001 ACL と二重管理になり漏洩リスク増・Principle III/IV に反する。却下。

---

## R9. No-train policy と provider no-train capability（FR-MFG-016〜020/029, G5, Base CR-001-B）

- **Decision**: **責務分離**を明確化する。002 は `DataUsePolicy`（`no_train_default=true` 固定既定、
  `training_opt_in` 既定 false、`opt_in_contract_ref`、`provider_no_train_required` 既定 true、
  `policy_version`）の保持・適用・governance 表示・opt-in 管理・audit を担う。001（Base CR-001-B）は
  provider ごとの **no-train 設定の検証・provider config 保存・provider 監査ログ連携** を担う。
  顧客データ（文書/画像/OCR/Excel/Word/PDF/メタデータ/質問/回答/引用/DraftArtifact/フィードバック/
  評価/ログ）は **opt-in 無しに学習・改善に使わない**。
- **GQ1 確定 → block**: ある capability（LLM/VLM/Embedding/OCR）に no-train を保証できる provider が
  存在しない場合、その capability は **既定で利用不可（block）**。tenant admin opt-in 上書きは MVP
  では提供しない。block 時は capability 由来の `temporarily_unavailable` として扱い、推測回答を
  返さない。
- **Rationale**: no-train by default（Hard Rule 7）を最も保守的に充足。warn＋opt-in（GQ1 案 b）は
  ガバナンス説明・契約管理の負荷と漏洩リスクを増やすため MVP では採らない。
- **Alternatives considered**:
  - GQ1=(b) warn＋opt-in で限定許可 → MVP で opt-in 契約フローと例外監査が必要。将来検討に回し、
    MVP は block。却下（MVP では block）。
  - 顧客データを既定でモデル改善に使い opt-out で停止 → SC-MFG-009 違反。却下。

---

## R10. Audit log coverage と tamper-evidence（FR-MFG-021〜023, Base CR-001-A）

- **Decision**: `AuditLogEntry` を **tenant-scoped・tamper-evident（hash chain）**・参照ID追跡で
  実装する。記録イベントは FR-MFG-021 の全 11 カテゴリ（ingest/metadata/approval/draft/high-risk/
  safety gate/answer/citation/feedback/ACL denial/admin setting/deletion）。各エントリは FR-MFG-022
  のフィールド（tenant_id/actor/action/resource/decision/reason/policy_version/
  high_risk_classification_result/safety_block_reason/approval_status_at_use/citation_ids/timestamp/
  request_id/source_ip ＋集計用 factory_id/department_id）を含む。**PII/secret/機密本文は保存せず**
  `document_id/chunk_id/citation_id/artifact_id` 等の参照IDで追跡（001 redaction を再利用）。tenant
  越え参照は禁止（001 tenant 分離を再利用）。tamper-evidence（hash chain）・export・retention は
  Base CR-001-A/C へ委譲し、002 MVP は構造化記録＋参照ID＋tenant スコープを先行実装。
- **Rationale**: safety telemetry/KPI の**単一真実源**（FR-MFG-030）として audit log を据えることで
  二重カウントを防ぐ。tamper-evidence と redaction を分離し、基盤共通機能は 001 へ巻き取る。
- **Alternatives considered**:
  - telemetry を audit と独立に集計 → 二重計上・不整合。却下（audit から導出）。
  - audit に本文を保存して検索性を上げる → SC-MFG-010（PII 混入 0）違反。却下（参照ID）。

---

## R11. Retention 既定値（FR-MFG-020, GQ2 確定）

- **Decision**: `DataUsePolicy.retention_period` の既定を **顧客データ 365 日 / 監査ログ 365 日**と
  し、tenant 単位で上書き可能（MVP ガイド: 下限 30 日・上限 3650 日）。retention 失効分は 001
  tombstone/カスケード [base:FR-008] と Base CR-001-C（retention/export）で削除する。export は tenant
  単位で `export_enabled` フラグに従う。
- **Rationale**: PoC/MVP ではデータ最小化を優先しつつ、監査トレースは運用・将来審査（ISMAP 見据え）
  に必要な最小期間を確保。tenant 上書きで業種別要件に対応。
- **Alternatives considered**:
  - 無期限保持 → データ最小化・no-train 方針と整合せず、漏洩面・コスト増。却下。
  - 監査 3 年（大企業審査寄り） → MVP では過剰。tenant 上書きで対応可能とし既定は 1 年。却下（既定）。

---

## R12. PoC KPI / Safety telemetry の計測（FR-MFG-014/028/030, G2/G3）

- **Decision**: 001 の EvaluationRunner / observability を再利用し、PoC KPI（`self_resolution_rate`/
  `average_time_to_answer`/`grounded_answer_rate`/`insufficient_evidence_rate`/`low_rating_rate`/
  `unanswered_question_count`/`frequently_referenced_documents`/`obsolete_document_candidates`/
  `expert_interruption_reduction`/`high_risk_query_count`/`safety_gate_block_count`）を計測・export
  する。`high_risk_query_count` と `safety_gate_block_count`（内訳: approved_citation_missing /
  insufficient_evidence / other_block）は **audit log から導出**し tenant/collection/factory/
  department/time range で集計。time range 粒度（hourly/daily/custom）は設定可能、retention は
  DataUsePolicy に従う。
- **Rationale**: G2/G3 で安全制御が「効いている件数」を可視化する要求を、新機構なしに audit 集計で
  実現。001 metrics/evaluation の baseline relative ゲートに KPI を載せる。
- **Alternatives considered**:
  - 独立 telemetry パイプライン → audit との二重管理・不整合。却下（audit 由来集計）。

---

## R13. Base Change Request の MVP 取り扱い（CR-001-A〜D）

- **Decision**: 002 は 001 を再定義しないため、横断要件は **Base CR-001-A〜D** として 001 側へ委譲
  する。ただし 002 MVP の vertical slice（FR-MFG-027）成立に必要な最小機能は solution layer 側で
  **先行実装**し、基盤統合時に 001 へ巻き取る:
  - CR-001-A（構造化 audit＋tamper-evidence＋export/retention）: 002 は構造化 `AuditLogEntry` 記録
    ＋参照ID＋tenant スコープを先行。hash chain/export は 001 へ。
  - CR-001-B（provider no-train capability 検証）: 002 は `provider_no_train_required` を尊重し、
    検証 API は 001 provider 抽象へ。
  - CR-001-C（retention/export）: 002 は `retention_period`/`export_enabled` を保持、削除実行は 001
    tombstone へ。
  - CR-001-D（platform security NFR）: 暗号化/脆弱性管理/バックアップ/インシデント対応は 001 の NFR
    として記録（FR-MFG-025、設計メモ）。
- **Rationale**: Principle IV（インターフェース経由）を保ち、002 を 001 の抽象に従属させる。MVP の
  PoC 成立と基盤の正しい責務配置を両立。
- **Alternatives considered**:
  - 002 内で audit/retention/security を完全実装 → 001 と二重化し基盤再定義に至る。却下（CR 委譲）。

---

## 未解決事項

**なし。** spec の Open Question（Q1/Q2/Q3）は解決済み。Governance CR の GQ1（→ block）/ GQ2
（→ 顧客 1 年・監査 1 年）は本 research（R9/R11）と spec の「Open Questions (Governance CR — 解決済み)」
で確定済み。NEEDS CLARIFICATION は残っていない。
