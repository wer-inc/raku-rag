# Implementation Plan: Manufacturing Field Knowledge RAG (Solution Layer)

**Branch**: `002-manufacturing-field-knowledge-rag` | **Date**: 2026-06-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-manufacturing-field-knowledge-rag/spec.md`

## Summary

製造業向け「現場ナレッジRAG」を **001-rag-platform の上に構築する solution layer** として実装する。
001 の tenancy / ACL pre-filter / ingestion / retrieval / answer / citation / groundedness /
evaluation / cost / visual RAG / deletion(tombstone) は **再定義せず再利用**し、本 layer は製造業
ドメイン固有の (1) 追加 parser（DOCX/XLSX/CSV）、(2) 製造業メタデータ＋承認メタデータ、(3) 類似
トラブル事例の知識活用、(4) DraftArtifact 生成＋軽量レビュー導線、(5) high-risk safety gate、
(6) PoC KPI / safety telemetry dashboard、(7) no-train policy・audit coverage の横断 governance
overlay を **001 の上に重ねる**。

設計の中核は「**安全側に倒す（fail-safe）**」をデータと制御フローに構造化することにある:

- **High-risk safety gate**: 文書メタデータ分類 ＋ クエリ意図分類の OR 判定（迷えば high-risk）。
  high-risk では **approved かつ有効な引用が無い限り断定しない**（001 groundedness gate に上乗せ）。
- **Draft-only 生成**: AI 生成物は必ず `status=draft` で作成され自動 approved にならない。
- **Reference-only knowledge**: 過去事例由来の対策は permanent でも「候補・参考」表示に正規化。
- **No-train by default ＋ audit coverage**: 顧客データは opt-in 無しに学習に使わず、規定イベントを
  tamper-evident な audit log に参照IDで記録する。

本 layer が必要とする 001 基盤の拡張は **新規 RAG 基盤を作らず Base Change Request（CR-001-A〜D）**
として 001 側へ委譲する（audit 構造化＋tamper-evidence / provider no-train capability 検証 /
retention・export / platform security NFR）。技術選択の詳細は [research.md](./research.md)。

**Clarifications 反映（Session 2026-06-19, /speckit-plan）**:
- **GQ1 → block**: no-train 保証 provider が無い capability は既定で利用不可（admin opt-in 上書きなし）。
- **GQ2 → 顧客 1 年 / 監査 1 年**: `DataUsePolicy.retention_period` 既定 365 日、tenant 上書き可。

## Technical Context

**Language/Version**: TypeScript/NestJS for synchronous API and Python 3.12 for parser/worker/evaluation code, following 001.

**Primary Dependencies**: 001 基盤を再利用（NestJS API / SQS worker / optional Dagster control plane / PostgreSQL+pgvector / OpenTelemetry / provider abstractions）。本 layer で追加する parser 依存（すべて 001 の `Parser` 抽象越し）: DOCX = `python-docx`、XLSX = `openpyxl`、CSV = stdlib `csv`。高リスク判定の LLM 分類は 001 の `LLMProvider` 抽象を再利用（新規 provider を作らない）。AWS MVP の ingestion は SQS + Python worker を既定とし、Dagster は manufacturing metadata enrichment / evaluation / KPI materialization の optional control plane / asset hook として利用可能にする。NestJS API は answer/search、DraftArtifact、review、dashboard API を担当する。

**Storage**: 001 と同一（PostgreSQL / Object Storage / Vector Store / SQS state / optional Langfuse）。PostgreSQL はアプリ状態、
document/chunk metadata、sync/processing state、approval、audit、cost、DraftArtifact を保持する。Object Storage は
raw files と parser artifacts、Vector Store は embeddings を保持する。製造業メタデータ・
承認メタデータは 001 `Document.metadata` / `Chunk.metadata`(JSON) に格納。製造業エンティティ
（Factory/Equipment/TroubleCase 等）・`DraftArtifact`・`DataUsePolicy`・`AuditLogEntry` は本 layer の
metadata テーブルとして追加（tenant_id 必須・001 ACL に従属）。

**Testing**: 001 と同一スイート構成（pytest / testcontainers / schemathesis）に、本 layer の
**safety hard gate** スイートを追加: (a) high-risk で approved 引用欠如時に断定しない（SC-MFG-006）、
(b) AI 生成物が draft 以外で自動確定されない（SC-MFG-007）、(c) obsolete/draft を正式根拠に
しない（SC-MFG-011）、(d) no-train opt-in 無しの学習利用 0（SC-MFG-009）、(e) 規定 audit イベント
記録率 100%・PII 混入 0（SC-MFG-010）。ACL/tenant 分離/削除再出現は 001 の hard gate を継承。

**Target Platform**: Linux server（コンテナ）。001 のモジュラモノリスに solution layer を同梱。

**Project Type**: web-service（API First）。製造業 solution layer は 001 と同一コードベース内の
追加モジュール群（`manufacturing/` パッケージ）として実装。PoC 用最小 Web UI / API demo は薄い層。

**Performance Goals**: 001 を継承（search/answer p95 を baseline で gate 化）。high-risk 判定の
追加レイテンシは answer p95 baseline に内包して回帰監視（LLM 分類はルール／キーワード先行で
短絡し、曖昧時のみ LLM）。

**Constraints**: safety hard gate を absolute（SC-MFG-006/007/008/009/010/011 = 違反 0）。
001 の ACL 漏洩ゼロ・削除済み再出現ゼロも継承。high-risk 判定は「迷えば high-risk」で fail-safe。
no-train block（GQ1）: no-train 非保証 capability は既定利用不可。

**Scale/Scope**: MVP は単一テナント PoC（vertical slice, FR-MFG-027）から開始し 001 と同じく水平
スケール可能。スコープは 7 ユーザーストーリー（US1 P1 / US2 P1 / US3 P2 / US4 P2 / US5 P3 /
US6 P2）＋ governance overlay。

## Constitution Check

*GATE: Phase 0 前に必須。Phase 1 設計後に再評価。*

本 layer は 001 基盤の原則充足を継承し、製造業ドメインで**強化のみ**を行う（弱める変更なし）。

| # | 原則 | 002 solution layer での充足 | 状態 |
|---|------|----------------------------|------|
| I | Groundedness First | 001 の 2 段階 gate を継承し、high-risk query では **approved かつ有効な引用必須**の safety gate を上乗せ（FR-MFG-005/007/015）。根拠不足は 001 同様 `insufficient_evidence`。生成物は draft 限定で断定しない | ✅ 強化 |
| II | Traceability | 製造業メタデータ・承認状態・DraftArtifact の `source_citations`/`source_document_ids`/`template_id`/`audit_log_ref` を 001 Citation/used_chunks に上乗せ。approval_status_at_use を回答・監査に伝播（FR-MFG-010b/022） | ✅ 強化 |
| III | Security by Design | 001 の tenant 分離・deny-by-default ACL・redaction・tombstone を再利用。部署/工場/役職/設備領域は **新規認可機構を作らず** 001 ACL group/role＋Factory/Process metadata へマッピング（FR-MFG-013）。audit coverage を製品イベントへ拡張（Base CR-001-A）、no-train（FR-MFG-016〜020） | ✅ 強化 |
| IV | Pluggable Architecture | DOCX/XLSX/CSV parser は 001 `Parser` 抽象に追加実装（既存利用側コード変更なし）。high-risk 判定の LLM 分類は `LLMProvider` 抽象越し。provider no-train capability 検証は Base CR-001-B として 001 provider 抽象へ | ✅ |
| V | Evaluation-Gated Delivery | 001 の EvaluationRunner に PoC KPI（FR-MFG-028）＋ safety telemetry（FR-MFG-030）を baseline relative で追加。safety hard gate（SC-MFG-006/007/009/010/011）は **absolute hard gate** | ✅ 強化 |
| VI | Observable by Default | 001 の OTel/metrics/構造化ログ＋redaction を継承。high-risk 判定・safety gate block・draft review・approval transition を audit/telemetry として記録（FR-MFG-021/030） | ✅ 強化 |
| VII | API First | 製造業機能（ingest+metadata / 類似トラブル / draft 生成・review / dashboard・KPI / safety telemetry）を **API として先行設計**（contracts/mfg-openapi.md）。最小 Web UI は API の消費者 | ✅ |
| VIII | Data Lifecycle Complete | 承認状態の状態遷移（draft→pending_review→approved→obsolete）と DraftArtifact 状態遷移（draft→in_review→approved/rejected/archived）を明示設計。削除は 001 tombstone/カスケードを再利用、retention/export は Base CR-001-C。フル DMS/任意版 rollback は非ゴール（明示） | ✅ |

**初期ゲート: PASS**（違反なし）。本 layer の追加要素（製造業 parser・safety gate・draft review・
governance overlay）はいずれも 001 の既存抽象・機構の**拡張または再利用**であり、具体実装への直接
依存や原則を弱める変更を導入しない。Complexity Tracking 不要。Phase 1 後の再評価は本ファイル末尾。

**Base Change Request の取り扱い**: CR-001-A〜D は 002 では実装せず 001 へ委譲する。002 の MVP は
これら CR の **最小実装版**（構造化 audit エントリの記録・provider no-train フラグの尊重・tenant
retention 設定の保持）を solution layer 側で先行し、基盤統合時に 001 へ巻き取る。これは原則 IV の
「インターフェース経由」を保つため、本 layer は 001 の抽象に追加する形でのみ実装する。

## Project Structure

### Documentation (this feature)

```text
specs/002-manufacturing-field-knowledge-rag/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output（技術選択・ドメイン判断）
├── data-model.md        # Phase 1 output（製造業エンティティ・承認・draft・audit）
├── quickstart.md        # Phase 1 output（PoC vertical slice 検証ガイド）
├── contracts/           # Phase 1 output
│   ├── mfg-openapi.md    #   solution-layer API（001 /v1 を拡張する /v1 エンドポイント）
│   └── mfg-interfaces.md #   solution-layer 抽象（HighRiskClassifier / SafetyGate / DraftGenerator …）
├── checklists/
│   └── requirements.md   # 既存
└── tasks.md             # /speckit-tasks で生成（本コマンドでは作らない）
```

### Source Code (repository root)

001 の `src/raku_rag/` モジュラモノリスに、製造業 solution layer を **`manufacturing/` パッケージ**
として同梱する（001 の `interfaces/`・`providers/`・`services/` を再利用し、本 layer 固有分のみ追加）。

```text
src/raku_rag/
├── interfaces/
│   └── base.py                  # 001: 13 抽象（再利用）。本 layer は追加抽象を manufacturing/ 側に置く
├── providers/
│   └── parsers.py               # 001 Parser 抽象。+ docx/xlsx/csv parser を追加実装（FR-MFG-001/002）
├── services/                    # 001 services（ingestion/retrieval/answer/groundedness…）を再利用
├── dagster/                     # 001 control plane。002 は manufacturing assets/checks/jobs を追加
│   ├── assets/manufacturing.py  # manufacturing_metadata_enriched_elements / dashboard metrics
│   └── checks/manufacturing.py  # high-risk approved citation / KPI / leakage checks
└── manufacturing/               # ★ 002 solution layer（本 feature が新規追加）
    ├── __init__.py
    ├── domain/
    │   ├── metadata.py          # ManufacturingDocumentMetadata（承認・safety 分類・製造業 tag）
    │   ├── entities.py          # Factory/Line/Process/Equipment/AlarmCode/Part/Product/Customer/
    │   │                        #   DefectType/FailureMode/TroubleCase/Countermeasure/WorkInstruction/
    │   │                        #   InspectionChecklist/QualityIssue/TrainingMaterial
    │   ├── draft.py             # DraftArtifact（状態遷移・reviewer・audit trail）
    │   ├── policy.py            # DataUsePolicy（no-train / retention / opt-in）
    │   └── audit.py             # AuditLogEntry（tenant-scoped, tamper-evident, 参照ID追跡）
    ├── safety/
    │   ├── classifier.py        # HighRiskClassifier（metadata×intent OR 判定, 迷えば high-risk）
    │   └── gate.py              # SafetyGate（approved 引用必須・obsolete warning・safety_block_reason）
    ├── ingestion/
    │   ├── metadata_enrichment.py  # 製造業メタデータ付与（ingest 時, 001 ingestion に hook）
    │   └── approval.py          # 軽量承認ワークフロー＋imported approval（FR-MFG-004/004a）
    ├── knowledge/
    │   └── trouble_cases.py     # 類似 TroubleCase 検索＋FailureMode/Countermeasure 一覧（FR-MFG-008/009）
    ├── drafts/
    │   ├── generator.py         # DraftGenerator（checklist/report/quality/training/faq, draft 限定）
    │   └── review.py            # ReviewWorkflow（draft→in_review→approved/rejected/archived）
    ├── governance/
    │   ├── no_train.py          # no-train policy 適用＋provider no-train 要求（Base CR-001-B 連携）
    │   └── retention.py         # retention/export（Base CR-001-C 連携; 既定 365 日）
    ├── telemetry/
    │   └── safety_metrics.py    # high_risk_query_count / safety_gate_block_count（audit 由来集計）
    ├── kpi/
    │   └── poc_metrics.py       # PoC KPI 計測・export（FR-MFG-028）
    └── api/
        ├── ingest_metadata.py   # ingest + 製造業メタデータ / approval API
        ├── trouble.py           # 類似トラブル検索 API
        ├── drafts.py            # draft 生成・review API
        ├── dashboard.py         # ナレッジ運用 dashboard + safety telemetry API
        └── policy.py            # DataUsePolicy / no-train governance API

tests/
├── security/                    # 001 hard gate（ACL漏洩/削除再出現/tenant 分離）を継承
├── integration/                 # 001 を継承
└── manufacturing/               # ★ 002 safety / draft / governance hard gate スイート
    ├── test_safety_gate.py      # high-risk approved 引用欠如→断定しない（SC-MFG-006）
    ├── test_draft_only.py       # AI 生成物 draft 以外自動確定なし（SC-MFG-007）
    ├── test_obsolete_draft_evidence.py  # obsolete/draft を正式根拠にしない（SC-MFG-011）
    ├── test_acl_mapping.py      # 工場/部署/役職/設備領域 ACL マッピング（SC-MFG-008, 001 ACL 再利用）
    ├── test_no_train.py         # opt-in 無し学習利用 0・no-train block（SC-MFG-009, GQ1）
    ├── test_audit_coverage.py   # 規定イベント記録率 100%・PII 混入 0（SC-MFG-010）
    └── test_safety_telemetry.py # high_risk/safety_block count 内訳（SC-MFG-013, FR-MFG-030）

poc-ui/                          # PoC 用最小 Web UI / API demo（FR-MFG-027; 後続・薄い層）
```

**Structure Decision**: 001 の web-service モジュラモノリスを**そのまま基盤として再利用**し、製造業
solution layer を `src/raku_rag/manufacturing/` という**独立パッケージ**として追加する。これにより
(1) 001 の `interfaces/`・`providers/`・`services/` への変更を最小化し（parser 追加のみ）、(2)
solution layer の境界を明確化し、(3) 横断 governance overlay（no_train/retention/audit/telemetry）を
`manufacturing/governance` 配下に集約する。第 3 の feature branch は作らない（spec G6: 001 基盤＋002
solution layer＋横断 overlay）。本 layer は 001 の抽象に従属し、ACL/tenant/tombstone は 001 機構を
そのまま強制する（新規認可・新規削除機構を作らない）。

**Analyze 整合メモ（2026-06-19, `/speckit-analyze` 由来）**:
- **API 二系統**: PoC/MVP の同期 API は本コードベースの **Python モジュール**（`src/raku_rag/manufacturing/api/*.py`）として実装する。上記 Technical Context の NestJS/TypeScript は **本番アダプタ（後続）** の同期 API を指し、001 と同じ二段構え（stdlib MVP → 本番アダプタ）とする。
- **010-industry-solution-framework は概念マッピングのみ**: spec の 010 参照は「Manufacturing IndustryProfile としても解釈できる」概念対応であり、002 は manufacturing semantics を自前で保持する。010 をビルド時依存にしない（依存は 001 のみ）。
- その他の整合解決（絶対ハードゲート 6 本の正典化・stdlib 先行・persistence パス・ACL 早期化）は `docs/loop-engineering.md` §8 を参照。

**責務境界（重要）**:
- **HighRiskClassifier**（`safety/classifier.py`）は判定のみ（metadata×intent → bool＋reason）。
- **SafetyGate**（`safety/gate.py`）は判定結果を受け、001 の groundedness gate **通過後**に
  「approved かつ有効な引用が無ければ断定を止める」制御と obsolete warning・`safety_block_reason`
  正規化を担う。安全機構を新設せず、001 gate に上乗せする 1 段。
- **DraftGenerator** は生成のみ・必ず `status=draft`。確定は **ReviewWorkflow** が reviewer 判断で
  行い、AI は自動 approved にしない（Hard Rule 1）。
- **safety telemetry / KPI** は **audit log を単一の真実源**として集計（二重カウントしない,
  FR-MFG-030）。新たな安全機構は作らない。

## Dagster Integration Boundary

002 は新しい orchestrator を作らず、001 の Dagster control plane に製造業向け asset / check / KPI hook を追加する。
Dagster はオンライン answer/search path には入らず、NestJS API がユーザー向け API、Q&A、DraftArtifact、review、
dashboard を担当する。PostgreSQL の app state が admin UI の正本であり、Dagster run は内部運用者向けの
参照情報として扱う。

**002 が Dagster に追加する責務**:
- `manufacturing_metadata_enriched_elements`: parsed elements / chunks に製造業メタデータ、承認メタデータ、
  safety/quality 分類を付与する asset。
- approval metadata checksum observation: `approval_metadata_checksum` だけが変わった場合、metadata update と
  safety/index filter update のみを行い、parse/chunk/embedding は再実行しない。
- manufacturing KPI materialization: PoC KPI と safety telemetry を日次または手動で materialize し、
  dashboard API は PostgreSQL の materialized result を読む。
- evaluation runs / quality checks: high-risk approved citation requirement、ACL leakage = 0、tenant isolation leakage = 0、
  deleted documents not searchable、spreadsheet citation cell_range valid、recall@k / citation accuracy baseline regression。

**002 が Dagster に持たせない責務**:
- request-time authorization decision（001 AclPolicy / tenant ACL が source of truth）。
- DraftArtifact state transition itself（`draft → in_review → approved/rejected/archived` は NestJS API + PostgreSQL）。
- review workflow state machine itself。
- audit log source of truth（AuditLogEntry は PostgreSQL が正本）。
- tenant ACL source of truth。

**UI / admin**:
App admin UI は PostgreSQL の IngestionRun / SourceSyncState / DocumentProcessingState / KPI materialization status を
表示する。必要に応じて `dagster_run_id` / run URL を内部運用者向けに表示するが、end user に Dagster UI を
直接見せない。

**Step Functions との関係**:
AWS-native な軽量 workflow は残してよいが、RAG document pipeline の差分同期、backfill、lineage、quality check は
Dagster を優先する。Lambda の 15 分制限に依存する重い parse/OCR/embedding は ECS/Fargate/worker/Dagster
executor 側へ逃がす。

## Complexity Tracking

> Constitution Check に違反が無いため記載不要。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （なし） | — | — |

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Dagster 運用コストと複雑性 | 001 基盤に加えて manufacturing asset/check/KPI job が増え、PoC の運用負荷が上がる | 002 は 001 Dagster control plane を再利用し、追加 asset は `manufacturing_metadata_enriched_elements` と KPI/checks に限定する |
| Draft/review state と Dagster run の責務混同 | DraftArtifact が pipeline run に引きずられ、review workflow の正本が曖昧になる | DraftArtifact と review workflow state machine は PostgreSQL + NestJS API が担当し、Dagster は生成根拠・KPI・evaluation materialization に限定する |
| approval metadata-only update の取りこぼし | high-risk safety filter が古い承認状態で判定し、approved 引用必須ルールが誤る | `approval_metadata_checksum` を SourceDocumentManifest に保持し、変化時は metadata/safety/index filter update を必ず materialize する |
| KPI materialization の鮮度不足 | dashboard が古い safety telemetry / PoC KPI を表示する | KPI daily materialization に加えて manual refresh を許可し、dashboard response に materialized_at / source_ingestion_run_id を返す |
| Dagster UI の誤公開 | end user に内部 pipeline 情報や source URI が露出する | App admin UI は PostgreSQL status を表示し、Dagster run URL は内部運用者ロールに限定する |

## Constitution Check (Post-Design Re-evaluation)

Phase 1 設計（data-model / contracts/mfg-openapi / contracts/mfg-interfaces / quickstart）反映後の
再評価: **PASS**。

- safety gate は 001 groundedness gate の**上乗せ 1 段**であり、approved-citation 必須・obsolete
  warning・safety_block_reason 正規化を構造化（I/VI 強化）。新規セキュリティ境界を作らず 001 の
  pre-filter/tombstone を再利用（III）。
- 製造業メタデータ・承認メタデータは 001 `Document.metadata`/`Chunk.metadata` に格納し、検索
  metadata filter（001 FR-010）で利用。製造業エンティティ・DraftArtifact・DataUsePolicy・
  AuditLogEntry は tenant_id 必須・001 ACL 従属の metadata テーブルとして追加（II/III）。
- DOCX/XLSX/CSV parser は 001 `Parser` 抽象への追加実装のみで、上位コード変更不要（IV）。
- PoC KPI ＋ safety telemetry を 001 EvaluationRunner に統合、safety hard gate を absolute gate に
  追加（V 強化）。
- audit coverage / no-train / retention は Base CR-001-A〜D として 001 へ委譲し、002 は policy/
  governance 表示と最小記録を担う責務境界を維持（III/VIII）。
- 新たな違反・正当化すべき複雑性なし → **PASS 継続**、Complexity Tracking 不要。
