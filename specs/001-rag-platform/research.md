# Phase 0 Research: Generic RAG Platform

**Feature**: `001-rag-platform` | **Date**: 2026-06-18

本ドキュメントは plan の Technical Context における技術選択と未確定事項を解決する。各項目は
**Decision / Rationale / Alternatives considered** 形式。中核方針は「特定技術に依存しすぎず、
主要コンポーネントをインターフェースで抽象化する」（Constitution Principle IV）。

---

## R1. Worker / Task Queue（SQS / Dagster / Step Functions）

**Decision**: AWS MVP は **SQS + DLQ + Python worker** を既定にする。`TaskQueue` インターフェースで抽象化し、RAG document pipeline の差分同期・backfill・reindex・evaluation・KPI materialization は `SourceSyncState` / `SourceDocumentManifest` / `DocumentProcessingState` / `IngestionRun` / `ReindexPlan` を介して Dagster control plane へ移行可能にする。

**Rationale**:
- 少人数 BtoB SaaS の MVP では SQS + DLQ が運用しやすく、AWS IAM/KMS/CloudWatch と一貫する。
- 重い parse/OCR/embedding は Lambda 15分制限に寄せず、Python worker / ECS Fargate / Dagster executor 側で実行する。
- 差分同期、backfill、embedding model migration、failed document retry、評価、KPI materialization が増えた段階で Dagster を control plane として使えるよう、状態モデルを先に持つ。

**Alternatives considered**:
- **Arq / Redis queue**: local/dev や軽量非同期には有効だが、AWS 本番の DLQ/IAM/運用説明では SQS を優先する。
- **Celery**: 成熟しているが、MVP の AWS-first 運用では SQS worker の方が小さい。
- **Step Functions**: AWS-native workflow には有効。ただし RAG 文書 pipeline の lineage/backfill/quality check は Dagster の方が適する。

---

## R2. Vector Store（pgvector / Qdrant / OpenSearch の比較）

**Decision**: MVP は **Aurora PostgreSQL Serverless v2 + pgvector + PostgreSQL RLS**。`VectorStore` インターフェースで抽象化。
スケール/ハイブリッド要件が顕在化した段階で **Qdrant**（性能）または **OpenSearch**
（BM25ハイブリッド＋日本語 analyzer）へ差し替える。

**Rationale**（最重要リスクとの整合）:
- **ACL pre-filter（最重要）**: メタデータ・ACL・tombstone が同一 PostgreSQL にあるため、
  ベクタ検索と ACL/テナント条件を **単一SQLで pre-filter** でき、post-filter 依存を避けられる
  （FR-022）。別データストアだと整合とフィルタ伝播が複雑化する。
- **削除整合（最重要）**: メタデータ削除・tombstone とベクタ削除を**同一トランザクション**で
  扱えるため、「削除済みが再出現しない」（SC-003 hard gate）を保証しやすい。
- 単一データストアで運用が単純。MVP規模の文書量で十分な性能。

**Alternatives considered**:
- **Qdrant**: 高速・payload filter・named vectors。ACLは payload filter で pre-filter 可能だが
  メタDBとの二重管理・削除整合の自前担保が必要。→ 性能スケール時の第一候補。
- **OpenSearch**: BM25＋kNN のハイブリッド、`kuromoji` で日本語 analyzer が強い。重い運用。
  → 日本語ハイブリッド検索を本格採用する段階の候補（R6参照）。

---

## R3. LLM / Embedding Provider 抽象化

**Decision**: `LLMProvider` と `EmbeddingProvider` の2インターフェースを定義し、以下を差し替え
可能にする。MVP の既定はコスト/品質バランスで選択（query profile で上書き可能）。
- **LLMProvider 実装**: OpenAI互換API、Azure OpenAI、Anthropic Claude、ローカル（Ollama 等）。
- **EmbeddingProvider 実装**: OpenAI互換、Azure OpenAI、ローカル Embedding（sentence-transformers 等）。

**Rationale**:
- Constitution Principle IV（差し替え可能）に必須。providerは capability（max context、
  embedding 次元、コスト単価、対応言語）をメタデータとして公開し、上位層が依存しない。
- Anthropic Claude を回答生成の有力な既定候補とする（長コンテキスト・根拠重視の回答に適する）。
  モデルIDは抽象の背後で設定: `claude-opus-4-8`（高品質）/ `claude-sonnet-4-6`（標準）/
  `claude-haiku-4-5-20251001`（低コスト・段階フォールバック）。query profile で cheaper model
  を選択可能（FR-033）。
- Embedding 次元差は `embedding_model_version` として Chunk に記録し、モデル変更時のみ
  再Embedding（FR-005a）。次元変更は index の再構築を伴うため migration として扱う。

**Alternatives considered**:
- 単一プロバイダ直結 → ベンダーロックインと障害単一点。却下。

> 注: 具体モデルの料金・コンテキスト上限・キャッシュ等は実装時に provider capability として
> 取得・設定する。本計画はモデル非依存（抽象越し）に保つ。

---

## R4. ACL / 認可の評価ポイント（pre-filter 設計）

**Decision**: 認可は **検索クエリ実行時に pre-filter**（SQL の WHERE 条件として ACL/tenant/
tombstone を適用）。reranker・LLM context・citation には pre-filter を通過したチャンクのみ
渡す。post-filter は二重防御としてのみ用い、単独では依存しない（FR-022, FR-014b）。

**Rationale**: ACL漏れが最重要リスク。pre-filter により「権限外チャンクが retrieval 段階で
そもそも取得されない」ことを構造的に保証する。LLM自己評価はセキュリティ境界にしない。

**実装方針**:
- 署名付きトークンの claims（`user_id`/`groups`/`roles`）を検証し、認可主体（principal）を構築。
- ACLは deny-by-default。許可は `tenant → collection → document` の階層 grant（user/group/role）。
- 検索SQL: `WHERE tenant_id = :tenant AND NOT tombstone AND acl_visible(principal)` を必須付与。
- 二重防御: retrieval 後に各チャンクの ACL を再評価する post-check を assert として実行
  （差分が出たら fail-closed＋アラート）。

**Alternatives considered**:
- post-filter のみ（取得後に除外）→ ベクタ index 側が権限を持たず漏洩リスク・性能劣化。却下。

---

## R5. 削除・tombstone・キャッシュ整合

**Decision**: 削除は **tombstone 即時化 → カスケード物理削除（非同期）** の2段階。
削除パスは `document → chunk → embedding → vector index → cache` の順で無効化。

**Rationale**: SC-003（再出現0件）は absolute hard gate。tombstone を検索SQLの必須条件にする
ことで、物理削除完了前でも即時に検索・回答・rerank・LLM context・citation から除外できる。

**実装方針**:
- `documents.tombstone`（または `deleted_at`）を全 retrieval クエリの必須フィルタに含める。
- キャッシュ（回答/retrieval/embedding）はキーに `tenant_id` と `document_version` を含め、
  削除/更新時に該当キーを invalidate。tombstone 文書を含む回答キャッシュは無効化。
- バックアップ復元後は deletion log / tombstone を再適用（FR-008a）。
- 物理削除は SQS/Python worker または Dagster cleanup job で非同期実行し、完了を IngestionRun / DocumentProcessingState で追跡。

---

## R6. 日本語対応（分割・検索・引用）

**Decision**:
- **チャンク分割**: 言語非依存の構造優先（見出し/段落/文境界）＋ token 数上限で確定。日本語は
  文境界・句読点（。！？）と heading を尊重し、空白/バイト分割をしない（FR-003a）。
- **検索**: MVP は vector-only ではなく、metadata exact filter + normalized identifier/code match + pgvector semantic search + bounded rerank。**hybrid search（BM25＋ベクタ）採用時**は Aurora 対応拡張を評価し、不足時は OpenSearch の `kuromoji` 等、日本語 tokenizer を利用（→ R2 のスケール差し替えと連動）。
- **引用**: 正規化テキストと原文の **offset mapping** を Chunk に保持。引用範囲は Unicode
  code point / grapheme cluster ベース（FR-003b）。

**Rationale**: 日本語は空白区切りがなく、バイト/空白基準の分割や引用は壊れる。offset mapping
により正規化（NFKC等）後の検索と原文表示の整合を取る。

**Alternatives considered**:
- 文字数固定窓分割 → 文の途中で切れ意味的まとまりを壊す。却下（構造優先にフォールバックとして
  のみ使用）。

---

## R7. 観測性（logging / metrics / tracing）

**Decision**: **OpenTelemetry** を横断トレースの標準とし、相関ID（trace_id）を ingestion〜
generation で伝播。メトリクスは Prometheus 互換、ログは構造化JSON（redaction 必須・FR-024a）。

**Rationale**: ベンダー中立（Principle IV/VI）。OTel exporter 差し替えで各APMに対応。段階別
（ingestion/indexing/retrieval/generation/evaluation）に span を張り、SC-005（トレース100%）。

---

## R8. 評価ランナー（検索品質・回答品質）

**Decision**: 独自の **EvaluationRunner** を実装。MVP指標 = recall@k・citation accuracy・
groundedness・p95 latency・query cost。CI ジョブ＋定期ジョブの両方から起動可能にする。

**Rationale**: FR-026/FR-028, SC-001/SC-006。検索/生成品質は **baseline relative gate**、
セキュリティ（ACL漏洩・削除再出現・テナント分離・権限外チャンク混入）は **absolute hard gate**。
groundedness/citation accuracy の判定は LLM-judge ＋ ルールベースの併用、judge は品質ゲート
であり権限境界にしない。

**Alternatives considered**:
- 既製フレームワーク（ragas 等）直結 → provider/judge をロックインしうるため、評価指標計算は
  内製しつつ judge provider は `LLMProvider` 抽象越しに利用。

---

## R9. プロジェクト構成・言語

**Decision**: AWS-first BtoB SaaS として、同期 API critical path は **NestJS / TypeScript**、parser/OCR/embedding/evaluation worker は **Python 3.12**、frontend/admin/chat は **Next.js + Vercel AI SDK**、infra は **AWS CDK TypeScript** とする。LangChain は中核 orchestration に採用せず、RetrievalOrchestrator / AnswerOrchestrator / CitationService / GroundednessService / RiskGateService / AuditService / CostService を明示的に持つ。

**Rationale**:
- tenant isolation、ACL pre-filter、approved/obsolete 制御、high-risk gate、no-train、audit、citation、DraftArtifact review は framework に隠すより service 層で明示した方が安全。
- NestJS は API/module boundary、OpenAPI、DI、BtoB SaaS の admin/control surface と相性が良い。
- Python は parser/OCR/layout/evaluation でエコシステムが強く、worker に閉じると API critical path を安定させやすい。
- CDK TypeScript はアプリ/API と同じ言語で AWS IaC を管理できる。

**Hosting note**: Vercel AI SDK は UI/streaming 実装に使ってよいが、Vercel hosting 自体は residency / telemetry / contractual requirements に従う。strict residency tenant では AWS-hosted Next.js を fallback とする。

---

## R10. 画像・ビジュアルRAG [CR: 画像RAG]

**Decision**: 画像処理を 4 つの新インターフェース（`OcrEngine` / `LayoutExtractor` /
`VisualEmbeddingProvider` / `VLMProvider`）として抽象化し、既存の retrieval/answer 経路へ
統合する。MVP は document 画像（スキャンPDF・図表・ページ画像）に限定し、音声/動画は非ゴール。

**取り込み・解析**:
- **OCR**: `OcrEngine` で抽出テキスト＋信頼度＋bounding box を取得。既定実装は差し替え可能
  （クラウドOCR / Tesseract 等のローカル）。日本語縦書き・帳票は精度差があるため provider 抽象に
  capability（対応言語・縦書き可否）を持たせる。OCRテキストは既存テキストチャンク経路に統合。
- **Layout / Region 抽出**: `LayoutExtractor` でページを paragraph/heading/table/figure/caption
  の region に分割し bbox/page/種別を付与。表・図は visual region として保持。

**Captioning（optional enrichment）**:
- `CaptioningProvider` で figure/chart/screenshot/image/page/region に `generated_caption_text`
  を生成。**検索補助のみ**で画像回答の一次根拠にしない（一次根拠＝元画像/page image/crop/visual
  region/OCR region）。tenant/collection/ingestion job/budget で enable/disable。
- caption にも PII/secret redaction を適用。失敗は ingestion 全体を落とさず `caption_status`
  に記録し再実行可。caption が不確実・曖昧・画像と矛盾する場合は推測回答しない（VLM が元画像/crop
  を確認）。**Rationale**: caption は recall を底上げするが幻覚し得るため、根拠ではなく検索ヒント
  に限定し、Groundedness First を侵さない。

**Embedding・検索**:
- **Visual Embedding**: `VisualEmbeddingProvider`（CLIP系/マルチモーダル埋め込み）。テキストと
  visual を**同一 retrieval 経路**で扱う。実装方針は (a) 共有マルチモーダル空間（テキストクエリ↔
  画像を直接比較）か (b) OCRテキストのテキスト埋め込み＋visual埋め込みのハイブリッド融合。MVPは
  **(b) ハイブリッド**を既定（OCRが効く文書画像で堅牢、ACL/フィルタは既存SQLに乗る）。共有空間は
  query profile で切替可能にする。
- **Visual Retrieval**: 既存 VectorStore に `modality` 列と visual ベクタを格納。ACL pre-filter・
  tenant 分離・tombstone 除外をテキストと同一の WHERE で適用（最重要リスクを再利用で担保）。

**回答生成**:
- **VLM**: `VLMProvider` で画像/region を根拠に回答。候補 = Anthropic Claude（vision 対応;
  `claude-opus-4-8` / `claude-sonnet-4-6`）、OpenAI互換 vision、Azure、ローカル VLM。`LLMProvider`
  とは別抽象にしつつ共通 capability（max images, context, unit cost）を公開。**VLM へ渡す画像・
  領域は検索済み∧権限確認済みのみ**（FR-040, ACL は VLM 前段で強制）。
- **Visual Citation**: 回答に `asset_id`・`page`・`bounding box`・OCR由来テキスト・score を付与。
  bbox は原画像座標系（正規化座標 0–1 を保持し解像度非依存）。

**Rationale**: 既存の「ACL pre-filter＋tombstone＋tenant 分離」を画像にそのまま再利用すること
で、最重要リスク（漏洩・再出現）を新モダリティでも構造的に担保。provider 抽象で OCR/VLM の
ベンダーロックインを回避（Principle IV）。

**Alternatives considered**:
- 共有マルチモーダル空間のみ（OCR無し） → 文字主体の文書画像で精度が落ち、テキスト引用が出せない。
  MVPでは却下、query profile の選択肢として残す。
- 画像をそのまま base64 で LLM に投げる単純実装 → ACL/region 引用/コスト制御ができず却下。

**評価指標の追加**: visual_recall@k・visual_citation_accuracy・bbox_iou・visual_groundedness・
p95 visual answer latency・visual query cost を baseline relative gate に組み込む（SC-008）。
visual query cost は OCR/captioning/visual embedding/VLM image token を含む。visual ACL漏洩
（asset/crop/OCR/caption）・削除再出現・テナント分離違反は absolute hard gate（SC-009）。

**コスト計測の粒度**: OCR cost / layout extraction cost / captioning cost / visual embedding
cost / **VLM image token cost（独立計測）** / thumbnail・crop generation cost / visual storage
cost を個別に記録（FR-044, L1）。

**EXIF**: 取り込み時に EXIF を検査し、GPS/端末情報など高リスクは既定で strip。保持時は policy＋
audit 対象（FR-043a）。

## 未解決 → Plan/Tasks へ送る設計事項（spec から継承）

- recall@k の **k の具体値**、検索/生成品質の暫定目標値（baseline 確定後に設定）。
- Vector index の **tenant 分離実装**（pgvector では `tenant_id` 列＋部分インデックス / RLS。
  Qdrant では collection-per-tenant / payload filter。OpenSearch では index-per-tenant）。
- **hybrid search の採否**と日本語 analyzer/tokenizer の最終選定。
- redaction エンジン（PII/secret 検出）の具体実装（正規表現＋辞書＋任意でNERモデル）。
- [CR:画像] OCR/LayoutExtractor/VisualEmbedding/VLM の **具体 provider 選定**と、visual 検索の
  既定方式（ハイブリッド融合 vs 共有マルチモーダル空間）の最終確定。
- [CR:画像] 画像内 PII の **領域マスク（redaction）実装**（顔/署名/身分証検出）と、原画像の保持/
  暗号化方針。
- [CR:画像] visual citation accuracy の評価データ作り方（期待 asset/page/bbox の正解付け）。

これらは MVP の抽象境界の内側で後から確定でき、アーキテクチャ選択をブロックしない。


---

## R11. Bedrock-first LLM / Embedding / Rerank Stack

**Decision**: LLM は Amazon Bedrock Claude、Embedding は Cohere Embed Multilingual v3 via Bedrock、Rerank は Cohere Rerank 3.5 via Bedrock を初期候補にする。Bedrock Guardrails は defense-in-depth とし、ACL / groundedness / RequiredEvidencePolicy / domain RiskGate の代替にしない。

**Rationale**:
- Amazon Bedrock FAQ は、customer content が base model 改善に使われず model provider に共有されないこと、暗号化や PrivateLink を説明している。BtoB SaaS の no-train / security explanation と相性が良い。
- Bedrock の rerank supported models には Cohere Rerank 3.5 (`cohere.rerank-v3-5:0`) が含まれる。
- Cohere Embed docs では `embed-multilingual-v3.0` が 1024 dimensions / 512 max tokens の multilingual embedding model として記載され、日本語も supported language list に含まれる。したがって chunk target は 250-400 tokens、max 約450 tokens にする。
- Bedrock Guardrails の prompt attack / sensitive filtering は有効な追加防御だが、domain-specific safety gates を置き換えない。

**Alternatives considered**:
- Titan embeddings: Bedrock-native fallback として PoC で比較する。
- OpenAI/Azure/Cohere direct: ProviderPolicy で許可された tenant のみ。default は Bedrock 経由を優先する。

References:
- Amazon Bedrock FAQ: https://aws.amazon.com/bedrock/faqs/
- Bedrock rerank supported models: https://docs.aws.amazon.com/bedrock/latest/userguide/rerank-supported.html
- Cohere Embed docs: https://docs.cohere.com/docs/cohere-embed
- Bedrock Guardrails prompt attack docs: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html

---

## R12. ParserProviderPolicy for Azure / Google / AWS-only Parsing

**Decision**: Parser/OCR provider は `ProviderPolicy` で tenant/collection 単位に制御する。default は AWS-only or customer-managed parser path。Azure Document Intelligence / Google Document AI は日本語表・スキャン精度の PoC 対象だが、strict residency / AWS-only tenant では opt-in なしに使わない。

**Rationale**:
- Azure Document Intelligence Layout は OCR と deep learning を組み合わせて text, tables, selection marks, document structure を抽出する。
- Google Document AI は document extraction / classification / OCR 系の候補であり、security/compliance docs で training/data handling を確認できるが、region/residency/contract は tenant policy と照合が必要。
- Amazon Textract は AWS-only path の候補。ただし日本語 OCR / layout は PoC で実測する。

**ProviderPolicy must record**:
- allowed parser providers
- provider region
- zero retention / no-train capability
- data residency requirement
- customer opt-in status
- fallback provider
- audit trail for provider changes

References:
- Azure Document Intelligence Layout: https://learn.microsoft.com/ja-jp/azure/ai-services/document-intelligence/prebuilt/layout?view=doc-intel-4.0.0
- Google Document AI: https://cloud.google.com/document-ai
- Google Document AI security/compliance: https://docs.cloud.google.com/document-ai/docs/security
- Amazon Textract FAQ: https://aws.amazon.com/textract/faqs/

---

## R13. Retrieval Strategy: Metadata / Code + Vector + Rerank

**Decision**: 初期検索は `metadata exact filter + identifier/code match + pgvector semantic search + bounded rerank`。vector-only は採用しない。

**Rationale**:
- 製造業、不動産、投資運用では `equipment_id`, `alarm_code`, `property_id`, `room_number`, `contract_id`, `fund_id`, `ISIN`, `invoice_id` など exact/code lookup が重要。
- Embedding は意味検索に強いが、識別子・型番・コードは exact / normalized keyword matching の方が安定する。
- Rerank は候補絞り込み後に使うことで cost/latency を抑える。

**Initial defaults**:
- vector top_k: 50
- metadata/code candidates: 20
- rerank input: max 50-80
- final context: 5-12

**Fallback paths**:
- Aurora PostgreSQL exact/FTS/extension で不足する場合: OpenSearch hybrid search。
- vector scaling が課題になる場合: Qdrant or OpenSearch via VectorStore abstraction。

---

## R14. Aurora pgvector + RLS Design Requirements

**Decision**: 初期 Vector DB は Aurora PostgreSQL Serverless v2 + pgvector + RLS。tenant/collection-aware partition/index plan と RLS hard tests を MVP 前に決める。

**Rationale**:
- AWS docs describe Aurora PostgreSQL with pgvector for vector storage/search.
- AWS Prescriptive Guidance documents row-level security recommendations for multi-tenant managed PostgreSQL.
- Metadata, ACL, approval, audit, cost, job state, and embeddings are colocated, which reduces consistency risk for tombstone and ACL pre-filter.

**Required design checks**:
- `tenant_id` on every retrievable row.
- RLS policies for application roles.
- session variable or equivalent tenant context for API, worker, admin, reindex, evaluation.
- no application-path bypass role.
- cross-tenant vector search hard tests.
- tenant/collection partitioning or partial/HNSW index plan.
- EXPLAIN plan benchmarks under realistic tenant filters.

References:
- Aurora PostgreSQL pgvector: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.VectorDB.html
- AWS RLS recommendations: https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-managed-postgresql/rls.html

---

## R15. Logging / Observability Policy

**Decision**: Langfuse self-hosted on ECS is allowed, but raw retrieved context is not stored by default. LoggingPolicy controls raw query/context/input/output storage, redaction, sampling, and retention per tenant/collection.

**Rationale**:
- Langfuse provides self-hosting options, which fits BtoB security review better than SaaS-only tracing.
- RAG prompts and retrieved context contain customer secrets, PII, and confidential financial/manufacturing/property data. Trace storage must be policy-gated.

**Default policy**:
- raw user query: redacted or disabled by tenant policy.
- retrieved context: disabled by default.
- citation IDs / chunk IDs: store.
- prompt template version: store.
- model metadata, latency, cost: store.
- model input/output: redacted unless opt-in.
- high-risk query: decision metadata stored; raw text policy-gated.

Reference:
- Langfuse self-hosting: https://langfuse.com/self-hosting

---

## R16. Evaluation PoC Plan

**Decision**: Before locking model/parser/search choices, run a two-stage PoC benchmark using 20-50 representative Japanese documents per industry profile: manufacturing, real estate property management, and investment management/mutual fund.

### Stage 1: Provider and parser benchmark

Evaluate:
- Cohere Embed Multilingual v3 vs Titan embeddings if needed.
- Azure Document Intelligence vs Google Document AI vs Textract / OSS parser.
- Parser output table/cell/citation quality for PDF, DOCX, XLSX, CSV, image, scanned PDF.

Metrics:
- parser table structure accuracy
- spreadsheet cell citation accuracy
- OCR/layout confidence
- chunk coverage
- embedding coverage
- p95 parse/index latency
- parse/index cost
- ProviderPolicy compliance

### Stage 2: Retrieval / answer benchmark

Evaluate:
- vector+rerank vs metadata/code+vector+rerank.
- optional hybrid search after baseline.
- Guardrails as defense-in-depth only.
- LoggingPolicy redaction and trace completeness.

Metrics:
- recall@5 / recall@10
- exact code lookup success rate
- citation accuracy
- spreadsheet cell citation accuracy
- groundedness
- insufficient evidence correct rejection rate
- high-risk gate compliance
- ACL leakage = 0
- tenant leakage = 0
- deleted document searchable = 0
- p95 latency
- query cost

**Evaluation tooling**: Ragas for faithfulness/answer relevancy/context precision/context recall where applicable, plus custom hard gates for ACL, tenant isolation, tombstone, high-risk required evidence, and logging redaction.

Reference:
- Ragas docs: https://docs.ragas.io/en/stable/

---

## R17. Runtime / IaC Fit

**Decision**: ECS Fargate is the default compute runtime for NestJS API, Python workers, Langfuse self-host, and optional Dagster components. AWS CDK TypeScript is the default IaC.

**Rationale**:
- AWS Fargate runs ECS containers without managing EC2 clusters and gives each task isolation boundaries.
- AWS CDK supports TypeScript as a stable client language, matching the API/IaC skillset.

References:
- AWS Fargate for ECS: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html
- AWS CDK TypeScript: https://docs.aws.amazon.com/cdk/v2/guide/work-with-cdk-typescript.html
