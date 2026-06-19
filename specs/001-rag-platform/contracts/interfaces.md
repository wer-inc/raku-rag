# Interface Contracts: Pluggable Components

**Feature**: `001-rag-platform` | **Date**: 2026-06-18 | Constitution Principle IV

`src/raku_rag/interfaces/` に定義する抽象。上位層（services/pipelines）は具体実装に依存せず、
これらの契約にのみ依存する。各実装は capability メタデータを公開し、差し替え可能（FR-031）。
署名は Python ABC の概念契約（型は実装時に Pydantic/typing で具体化）。

```python
# connector.py — 取り込み元の抽象（upload / object storage / future: Slack/Confluence）
class Connector(ABC):
    async def list_documents(self, source_config) -> AsyncIterator[RawRef]: ...
    async def fetch(self, ref: RawRef) -> RawContent: ...        # bytes + content_type + meta
    async def changes_since(self, cursor) -> ChangeSet: ...      # 差分同期(FR-005)

# parser.py — 正規化（PDF/MD/HTML/text, 日本語対応）
class Parser(ABC):
    @property
    def capability(self) -> ParserCapability: ...  # provider, supported_types, regions, zero_retention/no_train, table/cell support
    def supports(self, content_type) -> bool: ...
    def parse(self, raw: RawContent, *, provider_policy) -> NormalizedDoc: ...       # 原文 + 正規化text + offset基点

# chunker.py — メタデータ付きチャンク分割（構造/文境界, offset mapping; FR-003a/b）
class Chunker(ABC):
    def chunk(self, doc: NormalizedDoc, cfg: ChunkConfig) -> list[Chunk]: ...
    #  各 Chunk は heading_path, token_count, position, offset_mapping を持つ

# embedding.py — Embedding 生成（OpenAI互換/Azure/local）
class EmbeddingProvider(ABC):
    @property
    def capability(self) -> EmbeddingCapability: ...   # model_version, dim, langs, unit_cost, max_input_tokens
    async def embed(self, texts: list[str], *, embedding_job_id=None) -> list[Vector]: ...

# vector_store.py — ベクタ検索＋メタ/ACL pre-filter（pgvector/Qdrant/OpenSearch）
class VectorStore(ABC):
    async def upsert(self, tenant_id, chunks: list[ChunkVector]) -> None: ...     # tx対応
    async def search(self, tenant_id, query_vec, *, acl_filter, metadata_filter,
                     top_k, exclude_tombstoned=True) -> list[ScoredChunk]: ...
    #  acl_filter / exclude_tombstoned は実装側 pre-filter で必須適用(FR-022, R4)
    async def delete(self, tenant_id, chunk_ids) -> None: ...                     # cascade
    async def create_namespace(self, tenant_id) -> None: ...                      # tenant分離

# reranker.py — 任意の再ランク（失敗時はrerankなしで閾値判定; FR-030）
class Reranker(ABC):
    async def rerank(self, query, chunks: list[ScoredChunk], top_n) -> list[ScoredChunk]: ...

# llm.py — 回答生成（OpenAI互換/Azure/Anthropic/local）
class LLMProvider(ABC):
    @property
    def capability(self) -> LLMCapability: ...        # model, max_context, unit_cost, langs
    async def generate(self, prompt, context_chunks, *, params) -> LLMResult: ...
    #  context_chunks は「検索済み∧権限確認済み」のみ（制約; 呼び出し側が保証）

# task_queue.py — API 近傍の軽量非同期ジョブ（SQS/Step Functions/Celery/local adapter 等へ差し替え可; RAG document pipeline control plane は Dagster 互換）
class TaskQueue(ABC):
    async def enqueue(self, task: str, payload, *, retry, backoff, dlq=True) -> JobId: ...
    async def schedule(self, task: str, cron) -> None: ...      # 軽量タスク用。RAG 差分同期 schedule は Dagster sensors/schedules が担当
    def circuit_breaker(self, key) -> CircuitBreaker: ...       # FR-030

# --- [CR: 画像RAG] visual 抽象 ---

# ocr.py — 画像/スキャンPDF の文字抽出（cloud / tesseract 等）
class OcrEngine(ABC):
    @property
    def capability(self) -> OcrCapability: ...     # langs, 縦書き可否, unit_cost
    async def extract(self, image: ImageRef) -> list[OcrSpan]: ... # text + confidence + bbox

# layout.py — レイアウト/領域抽出（text/figure/table/chart/screenshot/form/caption）
class LayoutExtractor(ABC):
    async def extract(self, image: ImageRef) -> list[LayoutRegion]: ...  # type + bbox + page

# captioning.py — optional enrichment（検索補助; 一次根拠にしない; enable/disable 可）
class CaptioningProvider(ABC):
    @property
    def capability(self) -> CaptionCapability: ...   # model, langs, unit_cost
    async def caption(self, target: ImageRef) -> CaptionResult: ...
    #  CaptionResult: generated_caption_text + caption_confidence + status
    #  失敗は呼び出し側で caption_status=failed 記録（ingest 全体は落とさない; FR-050）
    #  生成 caption には redaction を適用（FR-049）。検索補助のみ（FR-048）

# visual_embedding.py — 画像/region のベクトル化（CLIP系/multimodal）
class VisualEmbeddingProvider(ABC):
    @property
    def capability(self) -> EmbeddingCapability: ...   # model_version, dim, modality, unit_cost
    async def embed(self, regions: list[ImageRef]) -> list[Vector]: ...

# vlm.py — Vision LLM による回答（Claude vision / OpenAI vision / Azure / local）
class VLMProvider(ABC):
    @property
    def capability(self) -> VLMCapability: ...     # max_images, max_context, unit_cost, langs
    async def generate(self, prompt, *, context_chunks, visual_regions, params) -> LLMResult: ...
    #  visual_regions は「検索済み∧権限確認済み」のみ（FR-040; 呼び出し側が pre-filter で保証）
```

## 横断コンポーネント（抽象 or ポリシー）

```python
# security: token検証 → principal、ACL pre-filter 条件の構築、二重防御 post-check
class TokenVerifier(ABC):
    def verify(self, signed_token) -> IdentityClaims: ...       # 署名検証(FR-025)
class AclPolicy(ABC):
    def visibility_filter(self, principal) -> AclFilter: ...    # deny-by-default, 階層grant
    def assert_visible(self, principal, chunk) -> None: ...     # 二重防御; 違反→fail-closed

# groundedness gate（FR-014）: pre-gate(score/evidence) + post-generation evidence check
class GroundednessGate(ABC):
    def pre_gate(self, scored: list[ScoredChunk], cfg) -> GateDecision: ...
    def post_check(self, answer, citations) -> GateDecision: ...   # 品質ゲート, 非セキュリティ

# redaction（FR-024）: PII/secret 検出・分類・マスキング
class Redactor(ABC):
    def classify(self, text) -> list[SensitiveSpan]: ...           # ingestion時タグ付け
    def redact(self, text, policy) -> str: ...                     # log/prompt/eval/error 必須
```


# provider_policy.py — provider/residency/no-train/zero-retention policy enforcement
class ProviderPolicyService(ABC):
    def validate(self, tenant_id, collection_id, operation, provider) -> ProviderDecision: ...
    def effective_policy(self, tenant_id, collection_id) -> ProviderPolicy: ...

# retrieval_profile.py — metadata/code + vector + rerank strategy
class RetrievalProfileService(ABC):
    def get(self, tenant_id, collection_id, retrieval_profile_id=None) -> RetrievalProfile: ...
    async def build_candidates(self, query, *, principal, filters, profile) -> CandidateSet: ...
    # CandidateSet combines metadata exact, identifier/code match, keyword (optional), vector, then bounded rerank.

# logging_policy.py — trace/log storage policy
class LoggingPolicyEnforcer(ABC):
    def redact_for_trace(self, payload, *, tenant_id, collection_id, data_kind) -> RedactedPayload: ...
    def should_store_raw(self, tenant_id, collection_id, data_kind) -> bool: ...

# guardrails.py — defense-in-depth only, not a security/evidence boundary
class GuardrailsAdapter(ABC):
    async def check_input(self, text, *, policy) -> GuardrailDecision: ...
    async def check_output(self, text, *, policy) -> GuardrailDecision: ...
    # Must not replace ACL, RequiredEvidencePolicy, GroundednessGate, or RiskGate.

## 契約テスト方針

- 各 interface に **共通契約テスト**（abstract conformance suite）を用意し、全実装に適用。
- VectorStore 実装は **ACL pre-filter / tombstone 除外 / tenant 分離** を契約テストで強制
  （security hard gate と連動; SC-003/004, FR-021a）。
- LLMProvider/EmbeddingProvider は capability 一貫性と差し替え互換を検証。
- ProviderPolicyService 契約テスト: external parser/OCR/LLM/embedding provider は policy/opt-in/residency/no-train 条件を満たさない限り拒否。
- RetrievalProfileService 契約テスト: metadata exact + identifier/code + vector + rerank の candidate union を検証し、vector-only default を禁止。
- LoggingPolicyEnforcer 契約テスト: raw retrieved context は default 保存不可、redaction/sampling/retention が守られる。
- [CR] VLMProvider 契約テスト: 渡された visual_regions 以外を根拠にしない（権限外画像を混ぜない）、
  visual citation に asset/page/bbox を返すことを検証。VisualEmbeddingProvider は modality 整合を検証。
