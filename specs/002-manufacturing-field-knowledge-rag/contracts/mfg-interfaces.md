# Interface Contracts: Manufacturing Solution Layer

**Feature**: `002-manufacturing-field-knowledge-rag` | **Date**: 2026-06-19 |
Constitution Principle IV（Pluggable）/ III（Security）/ I（Groundedness）

本 layer は **001 の 13 抽象を再利用**し（[001 interfaces](../001-rag-platform/contracts/interfaces.md)）、
製造業 solution layer 固有の抽象のみを `src/raku_rag/manufacturing/` 配下に追加する。安全機構・認可
機構・削除機構は**新設しない**（001 の groundedness gate / ACL pre-filter / tombstone に従属・上乗せ）。
署名は Python ABC の概念契約（型は実装時に Pydantic/dataclass で具体化）。

---

## 1. Parser 拡張（001 `Parser` 抽象への追加実装, FR-MFG-001/002）

001 の `Parser`（`supports(content_type)` / `parse(raw, content_type) -> normalized_text`）に DOCX/
XLSX/CSV を追加する。**新規抽象は作らず** 001 抽象の実装を増やす（Principle IV）。

```python
# providers/parsers.py に追加（001 Parser を実装）
class DocxParser(Parser):
    def supports(self, content_type) -> bool: ...   # application/vnd.openxmlformats...docx
    def parse(self, raw, content_type) -> str: ...   # 段落/表を正規化テキスト化

class SpreadsheetParser(Parser):
    """XLSX/CSV を行/列/シート構造を保持して正規化（FR-MFG-002）。"""
    def supports(self, content_type) -> bool: ...
    def parse(self, raw, content_type) -> str: ...
    #  各セルに sheet!R{row}C{col} アンカーを埋め、001 offset_mapping をセル座標へ写像
    #  → 001 Citation.text_range をセル引用範囲として解決可能にする
```

**契約テスト**: DOCX/XLSX/CSV のサンプルで (a) 正規化テキスト生成、(b) XLSX/CSV のセルアンカーが
引用範囲へ解決される、(c) 001 ingestion→search→answer 経路に未改造で載ることを検証。

---

## 2. MetadataEnricher（製造業メタデータ付与, FR-MFG-003/004/004a）

ingest 時に製造業メタデータ・承認メタデータを `Document.metadata` へ付与する（001 ingestion に hook）。

```python
class MetadataEnricher(ABC):
    @abstractmethod
    def enrich(self, doc_ref, raw_metadata) -> ManufacturingDocumentMetadata: ...
    #  equipment/model_no/alarm_code/defect_type/process/part_no/customer/document_type/
    #  safety_category/quality_category/equipment_operation_category/hazard_tags/process_id/
    #  equipment_id ＋ 承認メタデータ(approval_status/effective_date/.../approval_source) を返す

class ApprovalWorkflow(ABC):
    """軽量承認 draft→pending_review→approved→obsolete（FR-MFG-004）。"""
    @abstractmethod
    def transition(self, tenant_id, document_id, to_status, actor) -> ApprovalState: ...
    @abstractmethod
    def import_external(self, tenant_id, document_id, external) -> ApprovalState: ...
    #  approval_source=imported を source of truth として取り込む（FR-MFG-004a）
```

**契約テスト**: imported approval が source of truth として優先される、未提供時は workflow で補完、
全 transition が AuditLogEntry に記録される（FR-MFG-021）。

---

## 3. HighRiskClassifier（high-risk 判定, FR-MFG-015, research R2）

```python
class HighRiskClassifier(ABC):
    @abstractmethod
    def classify(self, query: str, candidate_metadata: list[ManufacturingDocumentMetadata]
                 ) -> HighRiskClassification: ...
    #  3 段カスケード: (1) metadata 分類タグ → (2) ルール+キーワード意図 → (3) 曖昧時のみ
    #  001 LLMProvider 抽象で意図分類。いずれか該当で is_high_risk=true（OR）。迷えば true。
    #  返り値: is_high_risk, reason_codes[], classification_source(metadata|rule|keyword|llm)
```

**契約テスト**: (a) hazard_tag を持つ文書 → high-risk、(b) 「分解して点検」等の意図 → high-risk、
(c) 曖昧クエリ → high-risk に倒す（fail-safe）、(d) 判定結果が audit に記録される。

---

## 4. SafetyGate（001 groundedness gate への上乗せ, FR-MFG-005/006/007, research R3）

001 `GroundednessGate`（pre_gate / post_check）の**後段に 1 段**追加する。**新規安全機構ではなく**
001 gate 通過後の安全側制御。

```python
class SafetyGate(ABC):
    @abstractmethod
    def evaluate(self, classification: HighRiskClassification,
                 candidate_citations: list[Citation],
                 candidate_metadata: list[ManufacturingDocumentMetadata]) -> SafetyDecision: ...
    #  is_high_risk のとき:
    #    - approved ∧ effective_date 有効な引用が無ければ blocked=true,
    #      safety_block_reason=approved_citation_missing → answer=insufficient_evidence(safety)
    #    - obsolete 文書参照は obsolete_warning=true（FR-MFG-006）
    #    - 危険作業は requires_onsite_confirmation=true（FR-MFG-007）
    #  safety_block_reason は相互排他 1 コードに正規化（優先順: approved_citation_missing
    #    → insufficient_evidence → other_block; FR-MFG-030）
    #  approval_status_at_use を SafetyDecision に記録（回答・監査へ伝播）
```

**契約テスト（safety hard gate, SC-MFG-006/011）**: high-risk × approved 引用欠如 → 断定しない
（blocked, reason=approved_citation_missing）。obsolete のみ → 一次根拠にせず warning。draft のみ →
正式根拠にしない。`safety_block_reason` が 1 ブロック 1 コードに正規化される。

---

## 5. TroubleCaseRetriever（類似事例の知識活用, FR-MFG-008/009）

```python
class TroubleCaseRetriever(ABC):
    @abstractmethod
    def find_similar(self, symptom_query: str, principal) -> list[TroubleCaseResult]: ...
    #  001 retrieval（ACL pre-filter）で TroubleCase 由来 Chunk を取得し、TroubleCase/FailureMode/
    #  Countermeasure を解決。Countermeasure は type(reference|candidate) と
    #  measure_class(provisional|permanent|unknown) を保持し、暫定/恒久を分けて返す。
    #  過去事例由来は permanent でも「候補・参考」に正規化（Hard Rule 4, FR-MFG-009）。
```

**契約テスト**: 症状クエリで類似 TroubleCase が原因/対策/再発防止/引用つきで返り、暫定/恒久が分離、
permanent でも候補ラベル、ACL 権限外の事例が出ない（001 pre-filter 再利用）。

---

## 6. DraftGenerator / ReviewWorkflow（ドラフト生成・レビュー, FR-MFG-010/010a/010b）

```python
class DraftGenerator(ABC):
    @abstractmethod
    def generate(self, kind, context_citations: list[Citation], template_id, actor
                 ) -> DraftArtifact: ...
    #  kind ∈ {checklist, trouble_report, quality_report, training, faq}
    #  返す DraftArtifact は必ず status=draft（自動 approved 禁止, Hard Rule 1, SC-MFG-007）
    #  source_citations/source_document_ids/template_id/created_by/audit_log_ref を付与
    #  安全項目は approved 根拠が無ければ断定しない（FR-MFG-011, FR-MFG-005 準拠）

class ReviewWorkflow(ABC):
    @abstractmethod
    def assign(self, artifact_id, reviewer_id_or_group) -> DraftArtifact: ...
    @abstractmethod
    def decide(self, artifact_id, reviewer, decision, comment) -> DraftArtifact: ...
    #  状態遷移 draft→in_review→approved|rejected|archived。approved は reviewer のみ。
    #  全 transition は AuditLogEntry へ（FR-MFG-021）。多段承認・電子署名なし。
```

**契約テスト（SC-MFG-007）**: 生成物は必ず draft、`created_by=ai` の自動 approved が拒否される、
FAQ も draft 扱い、approved 遷移は reviewer 判断のみ、全 transition が監査される。

---

## 7. Governance: NoTrainPolicy / RetentionManager（FR-MFG-016〜020/029, GQ1/GQ2）

```python
class DataUsePolicyStore(ABC):
    @abstractmethod
    def get(self, tenant_id) -> DataUsePolicy: ...        # no_train_default=true, opt_in=false 既定
    @abstractmethod
    def update(self, tenant_id, patch, actor) -> DataUsePolicy: ...  # 変更は audit 対象(FR-MFG-019)

class NoTrainGuard(ABC):
    @abstractmethod
    def assert_no_train(self, tenant_id, data_kind) -> None: ...
    #  opt-in 無しの学習/横断改善/別テナント改善利用を禁止（SC-MFG-009）
    @abstractmethod
    def capability_allowed(self, tenant_id, capability) -> bool: ...
    #  provider_no_train_required かつ no-train 保証 provider が無い capability は False（GQ1=block）
    #  → 呼び出し側は temporarily_unavailable（推測回答しない）

class RetentionManager(ABC):
    @abstractmethod
    def effective_retention(self, tenant_id) -> RetentionConfig: ...
    #  既定 顧客 365 日 / 監査 365 日（GQ2）、tenant 上書き可。失効は 001 tombstone へ委譲。
```

**契約テスト（SC-MFG-009）**: opt-in=false で学習利用が拒否される、no-train 非保証 capability が
block される（temporarily_unavailable, 推測なし）、retention 既定 365 日・上書きが効く。

---

## 8. AuditLogWriter / SafetyTelemetry（FR-MFG-021〜023/030, Base CR-001-A）

```python
class AuditLogWriter(ABC):
    @abstractmethod
    def record(self, entry: AuditLogEntry) -> None: ...
    #  tenant-scoped・参照IDのみ（PII/secret/本文を保存しない, SC-MFG-010）。
    #  tamper-evidence(hash chain): prev_hash/entry_hash を連結（Base CR-001-A）。
    #  tenant 越え参照禁止（001 tenant 分離再利用）。

class SafetyTelemetry(ABC):
    @abstractmethod
    def aggregate(self, tenant_id, *, axis, time_range) -> SafetyTelemetryResult: ...
    #  audit log を単一真実源として high_risk_query_count / safety_gate_block_count(内訳) を集計。
    #  axis ∈ {collection, factory, department}; 二重カウントしない（FR-MFG-030）。
```

**契約テスト（SC-MFG-010/013）**: 規定イベント記録率 100%・PII 混入 0、tenant 越え参照拒否、
telemetry が audit 由来で内訳（approved_citation_missing/insufficient_evidence/other_block）を
相互排他に集計、factory/department 軸で集計できる。

---

## 横断: 001 抽象の再利用一覧（再定義しない）

| 001 抽象 | 002 での使い方 |
|---|---|
| `Parser` | DOCX/XLSX/CSV 実装を追加（§1） |
| `VectorStore`（ACL pre-filter / tombstone） | 検索・TroubleCase 取得で再利用。新規検索機構なし |
| `LLMProvider` | high-risk LLM 分類（§3）・draft 生成（§6）で再利用 |
| `GroundednessGate` | SafetyGate が後段に上乗せ（§4）。基盤 gate は改造しない |
| `TokenVerifier` / `AclPolicy` | 部署/工場/役職/設備領域マッピング（FR-MFG-013）。新規認可なし |
| `Redactor` | audit の PII/secret 非保存（§8）で再利用 |
| `OcrEngine`/`LayoutExtractor`/`VLMProvider` 他 visual | スキャン点検表・図面の取り込み（US2/PoC）で再利用 |

---

## 契約テスト方針（まとめ）

- 各 mfg 抽象に共通契約テスト（abstract conformance suite）を用意し、全実装に適用。
- **safety hard gate**（SafetyGate/DraftGenerator/NoTrainGuard/AuditLogWriter）は 001 の security
  hard gate と同様 **absolute gate**（SC-MFG-006/007/009/010/011 = 違反 0）として CI で強制。
- 001 の ACL 漏洩 / 削除再出現 / tenant 分離テストは継承（製造業エンティティ・DraftArtifact・
  audit にも tenant 越え参照禁止を適用）。
