# Feature Specification: Generic RAG Platform

**Feature Branch**: `001-rag-platform`

**Created**: 2026-06-18

**Status**: Draft

**Input**: User description: 汎用的なRAGプラットフォームを設計する。複数の業務アプリケーションや社内ツールから共通利用できるRAG基盤を提供する。

## Clarifications

### Session 2026-06-18

- Q: マルチテナント分離の主境界はどの単位か（tenant / project / collection）？ → A: **tenant** を最上位のハード分離境界とし、collection/project は tenant 内のサブグルーピング。全 document/chunk/embedding/job/evaluation/audit log/cache entry は `tenant_id` を必須で持つ。検索・ACL・監査・コスト集計は tenant→collection→document の階層で評価。クロステナント検索は MVP で禁止。Vector index は tenant 単位の namespace/partition/index 分離を必須とし、実装方式は plan で決定。
- Q: 鮮度（差分同期・再Embedding）のタイミングは？ → A: 差分同期は (1) スケジュール実行 (2) オンデマンド/手動 (3) 将来の webhook/event-driven をサポート。再Embeddingは `content checksum` / `chunking configuration` / `embedding_model_version` のいずれかが変化した場合のみ。同期頻度と stale 許容時間は tenant/collection 単位で設定可能。レスポンスに source freshness / indexed_at / document_version を含められるようにする。
- Q: コスト上限と節約戦略は？ → A: tenant/collection/query 単位で cost budget を設定可能。LLM token・embedding token・rerank・storage・indexing job のコストを記録。節約戦略 = embedding cache / checksum による再Embedding抑制 / rerank 上位N件限定 / query profile による cheaper model・smaller top_k・rerank skip / 回答・retrieval キャッシュ / budget 超過時の graceful degrade。ただし graceful degrade で根拠不足判定や ACL を弱めてはならず、安全に回答できない場合は `budget_exceeded` / `temporarily_unavailable` を返す。
- Q: PII/secret・ログ・プロンプト・評価データの扱いは？ → A: 取り込み時は PII/secret の検出・分類・タグ付けを行う（全コンテンツ一律 redaction は必須にしない。tenant/collection の policy に応じて indexing前 redaction / 回答時 redaction / authorized retrieval を選択可能）。ログ・トレース・プロンプト保存・評価データ・フィードバック・エラー出力には redaction/masking を必須適用。secret 判定値は原則これらに保存しない。評価データ登録時は PII/secret scrub を必須チェック。redaction済みデータと原文の扱いは audit log で追跡可能にする。
- Q: 日本語対応で考慮すべきことは？ → A: 日本語を MVP 対象に含める。チャンク分割は空白・バイト長に依存せず、文境界・句読点・見出し・段落・意味的まとまり・token count を考慮。日本語見出しは heading_path に保持。検索は日本語・多言語対応 embedding を使用（hybrid search 採用時は日本語向け analyzer/tokenizer を plan で検討）。引用範囲は Unicode code point / grapheme cluster ベースで扱い、正規化テキストと原文テキストの offset mapping を保持して引用表示が原文上で正しく対応するようにする。

### Session 2026-06-18 — CR: 画像RAG対応

- CR: 既存 feature `001-rag-platform` に **画像・ビジュアル文書RAG** を追加（新 spec / branch は作らない差分更新）。対象範囲 = 画像 / スキャンPDF / 図表を含む文書の取り込み、visual asset storage、OCR、layout/region 抽出、visual embedding、visual retrieval、VLM（Vision LLM）による回答生成、visual citation（page + bounding box）。**リアルタイム音声・動画RAG は引き続き非ゴール**（静止画・文書画像・ページ画像のみ）。
- CR 制約: 既存の Groundedness / Traceability / Security / マルチテナント / 削除 / コスト / 評価の全制約を画像モダリティにも同等に適用する。visual asset・layout region・visual chunk・crop にも `tenant_id` と ACL を必須とし、document の ACL を継承。削除は tombstone＋カスケードで visual asset / OCR テキスト / region / crop / generated caption / visual embedding / サムネイル / 各種 cache まで及ぶ。retrieval は ACL pre-filter、VLM へ渡す画像・領域も権限確認済みに限定する。
- CR: **captioning は optional enrichment**。図表・画像・スクリーンショット・PDFページ・layout region に対し自動キャプション（`generated_caption_text`）を生成できるが、tenant/collection/ingestion option/cost budget で有効・無効を切り替えられる。生成キャプションは**検索補助**に用い、画像内容に関する回答の**一次根拠としては扱わない**（一次根拠＝元画像 / page image / crop / visual region / OCR region）。caption のみで裏付けできない場合は VLM が元画像または crop を確認し、caption が不確実・曖昧・画像と矛盾する場合は推測回答をしない。`region_type=caption`（レイアウト種別）と `generated_caption_text`（生成物）は区別する。

### Session 2026-06-21 — CR: RAG performance guardrails

- CR: production answer path は **measurement first** とし、1リクエストごとに `request_id`、hash 化した `tenant_id/user_id`、`llm_call_count`、`retrieval_ms`、`rerank_ms`、`generation_ms`、`total_ms`、`retrieved_chunks`、`rerank_input_count`、`context_tokens`、`prompt_tokens`、`completion_tokens`、`cache_hit` を記録する。raw query / raw context / raw identity は既定で保存しない。
- CR: 同期 RAG hot path の性能予算を QueryProfile/RetrievalProfile で制御する。既定は `max_synchronous_llm_calls=1`、`vector_top_k=50`、`rerank_candidate_limit=20`、`final_context_limit=8`、`max_context_tokens=8000` とし、query rewrite / HyDE / LLM judge / citation deep validation は常時同期実行しない。
- CR: ACL・tenant・業界 metadata filter は検索時点で pushdown し、post-filter のみに依存しない。rerank 対象数、最終 context chunk 数、context token 数は上限を必須にし、p50/p95/p99・同時実行・large corpus/many tenants/long document を performance readiness gate で検証する。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 根拠付き回答を得る (Priority: P1)

エンドユーザーが自然言語で質問し、取り込み済みの社内文書に基づいた回答を、引用元（出典文書・該当箇所）とともに受け取る。根拠が不足する場合は、推測ではなく「根拠不足」と返される。

**Why this priority**: これがプラットフォームの中核価値。取り込み・検索・生成・引用・根拠不足判定が揃って初めて、利用者が「信頼できる回答基盤」として使える最小の成立単位になる。これ単体で価値が出るMVPの心臓部。

**Independent Test**: 既知の文書セットを取り込んだ状態で、(a) 文書に答えがある質問→引用付き回答が返る、(b) 文書に答えがない質問→「根拠不足」が返る、の2系統で検証できる。

**Acceptance Scenarios**:

1. **Given** 回答根拠を含む文書が取り込み済み, **When** ユーザーが関連する質問をする, **Then** 回答と、`document_id`・`chunk_id`・該当テキスト範囲を含む引用、および使用チャンク一覧が返る。
2. **Given** どの文書にも回答根拠が存在しない質問, **When** ユーザーが質問する, **Then** システムは推測で回答せず「根拠不足」を明示して返す。
3. **Given** 複数文書に部分的な根拠が分散している, **When** ユーザーが質問する, **Then** 回答は実際に引用したチャンクのみを出典として列挙し、引用していない文書を出典に含めない。

---

### User Story 2 - データソース取り込みと取り込み管理 (Priority: P1)

管理者がデータソース（アップロードファイル、ローカル/オブジェクトストレージ上の文書）を登録し、取り込みジョブを実行する。システムは文書を解析・正規化・チャンク分割・Embedding化・インデックス登録する。管理者はジョブ状態・失敗理由・再実行・削除・再インデックスを管理できる。

**Why this priority**: User Story 1 が成立するためのデータがこの経路でしか入らない。取り込みと、その状態可視化・失敗回復はMVPに不可欠。

**Independent Test**: PDF/Markdown/HTML/プレーンテキストの各サンプルを登録→取り込みジョブを実行→ジョブが成功状態になり、生成チャンク数・インデックス登録が確認でき、意図的に壊した文書では失敗理由が記録され再実行できることで検証できる。

**Acceptance Scenarios**:

1. **Given** PDF・Markdown・HTML・プレーンテキストの文書, **When** 管理者が取り込みジョブを実行, **Then** 各文書が正規化され、メタデータ付きチャンクに分割され、Embeddingが生成されインデックスに登録される。
2. **Given** 取り込みに失敗した文書, **When** 管理者がジョブ一覧を確認, **Then** 失敗理由が表示され、その文書だけを再実行できる。
3. **Given** 取り込み済み文書, **When** 管理者が当該文書を削除, **Then** 文書とその全チャンクがインデックスから除去され、以後の検索・回答に再出現しない。
4. **Given** 取り込み済み文書のソース側が更新された, **When** 差分同期が実行される, **Then** 変更分のみ再取り込みされ（checksum比較）、旧バージョンのチャンクは置き換えられる。

---

### User Story 3 - アプリ開発者によるAPI組み込み (Priority: P2)

アプリ開発者が、自分のアプリから ingest / search / answer / feedback / admin の各操作をAPI経由で呼び出し、自社アプリにRAG機能を組み込む。

**Why this priority**: 「複数アプリから共通利用」という目的の実現手段。中核機能(P1)が安定した契約面として外部公開されて初めて目的を満たすが、機能そのものはP1に依存するためP2。

**Independent Test**: APIクライアントから search と answer を呼び、レスポンスに追跡識別子（source_id/document_id/chunk_id/version/retrieval_score）と引用が含まれることを検証できる。

**Acceptance Scenarios**:

1. **Given** 有効な認証情報を持つアプリ, **When** search APIを top_k・metadata filter 指定で呼ぶ, **Then** 各検索結果に `source_id`・`document_id`・`chunk_id`・`version`・`retrieval_score` が含まれて返る。
2. **Given** 有効な認証情報を持つアプリ, **When** answer APIを呼ぶ, **Then** 根拠付き回答・引用・信頼度・使用チャンク一覧が返る。
3. **Given** 後方非互換なAPI変更が必要な状況, **When** 新バージョンを公開する, **Then** 既存バージョンのAPI契約は維持され、バージョンを明示して提供される。

---

### User Story 4 - 品質評価とフィードバック (Priority: P2)

管理者が評価用の質問・期待回答・期待根拠を登録し、検索品質・回答品質・引用品質を測定する。ユーザーや評価ジョブが回答にフィードバックを付ける。回帰があればリリースをブロックする。

**Why this priority**: Evaluation-Gated Delivery 原則の実装。品質の継続確認と回帰防止に必須だが、P1の機能が存在して初めて測定対象が生まれるためP2。

**Independent Test**: 評価データセット（質問・期待回答・期待根拠）を登録し評価ジョブを実行→recall@k・citation accuracy・groundedness のスコアが算出され、ベースラインとの比較で回帰が検出されることで検証できる。

**Acceptance Scenarios**:

1. **Given** 登録済み評価データセット, **When** 評価ジョブを実行, **Then** recall@k・citation accuracy・groundedness・レイテンシ・コストが算出され、ベースラインと比較される。
2. **Given** ベースラインに対し品質が回帰した候補, **When** リリース判定を行う, **Then** 評価ゲートがリリースをブロックする。
3. **Given** 返された回答, **When** ユーザーがフィードバックを付与, **Then** フィードバックが回答・引用に紐づけて保存される。

---

### User Story 5 - 運用監視 (Priority: P3)

運用者が、検索失敗・低品質回答・コスト増加・遅延・失敗ジョブを監視し、各処理（ingestion / indexing / retrieval / generation / evaluation）をトレースできる。

**Why this priority**: 継続運用に必要だが、Observable by Default 原則により各機能実装時に観測点が埋め込まれる前提のため、独立した可視化レイヤーとしてはP3。

**Independent Test**: 1件の質問リクエストが ingestion〜generation の各段階を相関IDで横断追跡でき、レイテンシ・エラー率・コストのメトリクスが参照できることで検証できる。

**Acceptance Scenarios**:

1. **Given** 実行中のシステム, **When** 運用者がメトリクスを参照, **Then** 段階別のレイテンシ・スループット・エラー率・クエリあたりコストが確認できる。
2. **Given** 1件のリクエスト, **When** 運用者がトレースを追う, **Then** 取り込み・検索・回答生成を相関IDで横断追跡できる。

---

### User Story 6 - 画像・ビジュアル文書のRAG (Priority: P2) [CR: 画像RAG]

エンドユーザーが、画像・図表・スキャンPDF・ページ画像を含む文書に対して質問し、**該当ページ・該当領域（bounding box）を引用**した根拠付き回答を受け取る。画像内テキストは OCR で抽出され、図表・レイアウトは region として扱われ、VLM（Vision LLM）が権限確認済みの画像/領域のみを根拠に回答する。

**Why this priority**: テキストRAG（US1）が成立したうえで対象モダリティを拡張する位置づけ。中核の検索・回答・引用・根拠不足・ACL・削除の枠組みを画像に拡張するため P2。テキスト経路に依存する。

**Independent Test**: スキャンPDF/画像/図表入り文書を取り込み、(a) 画像内テキストに答えがある質問→該当ページとbboxを引用した回答、(b) 図表に関する質問→該当region引用、(c) 権限外の画像→結果・回答・引用・VLM入力に出ない、で検証できる。

**Acceptance Scenarios**:

1. **Given** スキャンPDF/画像文書が取り込み・OCR・region抽出・visual embedding 済み, **When** ユーザーが画像内容に関する質問をする, **Then** 回答に `asset_id`・`page`・`bounding box`・引用テキスト（OCR由来）を含む visual citation と used_chunks が返る。
2. **Given** 図表を含む文書, **When** ユーザーが図表に関する質問をする, **Then** 該当 layout region を引用し、引用していない領域を出典に含めない。
3. **Given** 画像にもOCRにも回答根拠が無い, **When** ユーザーが質問する, **Then** 推測せず「根拠不足」を返す。
4. **Given** 権限のない visual asset, **When** ユーザーが質問する, **Then** 当該画像・領域は retrieval result・rerank・VLM入力・citation のいずれにも含まれない。
5. **Given** visual asset を含む文書を削除, **When** 削除後に質問する, **Then** 画像・OCRテキスト・region・visual embedding・サムネイル・cache から即時除外され再出現しない。

---

### Edge Cases

- 権限のない文書しかヒットしない質問では、システムは制限文書の内容を一切露出せず「根拠不足」として扱う。
- 検索結果のスコアがすべて閾値未満の場合、推測回答をせず「根拠不足」を返す。
- 取り込み中に文書がソース側で削除/更新された場合、ジョブは一貫した状態（部分適用を残さない）で終了する。
- 同一文書の再取り込みで version と checksum が変わらない場合、再Embedding・再インデックスをスキップする。
- LLM / Embedding / Vector Store / Parser / Reranker / Connector の障害時は、FR-030 のコンポーネント別 fail-closed 方針に従い、回復不能ならエラーを明示し部分結果で誤誘導しない。
- 最大文書サイズ・最大チャンク数の上限を超える入力は、取り込み時に明示的に拒否され理由が記録される。
- 削除要求の対象がバックアップにのみ残る場合も、削除が完全に履行され、復元時には tombstone/deletion log が再適用される。
- cost budget を超過した場合、推測回答をせず `budget_exceeded` を返す（根拠不足判定・ACL は弱めない）。
- 別テナントのデータを参照しようとするクロステナント検索要求は拒否される（MVPでクロステナント検索は禁止）。
- [CR:画像] OCR でテキストが抽出できない画像（写真のみ等）は、visual embedding による検索のみ対象とし、テキスト引用は付さず該当領域（bbox）を引用する。
- [CR:画像] OCR の信頼度が閾値未満の領域は、根拠として採用せず（または信頼度を低減して扱い）、推測回答に使わない。
- [CR:画像] VLM が画像内容を根拠付けできない場合は、テキスト同様に「根拠不足」を返す（post-generation evidence check を画像引用にも適用）。
- [CR:画像] VLM provider 障害時は fail-closed とし、回答生成せず `temporarily_unavailable` を返す（OCRテキストだけで推測しない）。
- [CR:画像] 画像内に PII（顔・署名・カード番号等）が検出された場合、policy に従い retrieval/回答時に該当領域をマスク（redaction）し、ログ・評価データに原画像を残さない。
- [CR:performance] reranker 入力、最終 context chunk 数、context token 数が profile 上限を超える場合は、上限内に切り詰めるか `insufficient_evidence` / `temporarily_unavailable` を返し、無制限に prompt へ詰め込まない。
- [CR:performance] query rewrite / HyDE / LLM judge / citation deep validation などの追加 LLM call は、`max_synchronous_llm_calls` を超える場合は同期 hot path では実行せず、非同期 sampling / eval / CI に回す。
- [CR:performance] ACL・tenant・metadata filter を検索後アプリ側で大量に捨てるだけの実装は不可。DB/index 側の pre-filter が無効な場合は performance/security risk として trace と readiness report に記録する。

## Requirements *(mandatory)*

### Functional Requirements

**取り込み・データライフサイクル**

- **FR-001**: システムは、アップロードファイルおよびローカル/オブジェクトストレージ上の文書を取り込めなければならない。
- **FR-002**: システムは、PDF・Markdown・HTML・プレーンテキストを正規化できなければならない。[CR:画像] さらに、画像（PNG/JPEG/TIFF 等）およびスキャンPDF・図表を含む文書を取り込み対象に含めなければならない。リアルタイム音声・動画は対象外（非ゴール）。
- **FR-003**: システムは、文書をメタデータ付きチャンクに分割できなければならない。
- **FR-003a**: システムは日本語文書を MVP の対象に含めなければならない。チャンク分割は空白やバイト長に依存せず、文境界・句読点・見出し・段落・意味的まとまり・モデルの token count を考慮しなければならない。日本語見出しは heading_path に保持する。
- **FR-003b**: システムは、正規化テキストと原文テキストの offset mapping を保持し、引用範囲を Unicode code point / grapheme cluster ベースで扱い、引用表示が原文上で正しく対応するようにしなければならない（マルチバイト文字を壊さない）。
- **FR-004**: システムは、チャンクのEmbeddingを生成し検索インデックスに保存できなければならない。
- **FR-005**: システムは、差分更新（checksum比較による変更検出）・削除反映・再インデックスをサポートしなければならない。差分同期は (1) スケジュール実行 (2) オンデマンド/手動実行 (3) 将来の webhook/event-driven sync をサポートする。
- **FR-005a**: 再Embeddingは `content checksum` / `chunking configuration` / `embedding_model_version` のいずれかが変化した場合のみ実行しなければならない。同期頻度と stale 許容時間は tenant/collection 単位で設定可能とする。
- **FR-005b**: 検索・回答レスポンスには、必要に応じて source freshness / `indexed_at` / `document_version` を含められるようにしなければならない。
- **FR-006**: システムは、取り込みジョブの状態・失敗理由を記録し、個別文書の再実行・削除・再インデックスを可能にしなければならない。
- **FR-007**: システムは、バックアップを保持し、一貫した状態へのロールバック/復元ができなければならない。
- **FR-008**: 削除は document → chunk → embedding → vector index → cache の順でカスケード無効化しなければならない。削除要求を受け付けた時点で対象 document を **tombstone 状態** にし、検索・回答・引用・rerank・LLM context から即時除外しなければならない。物理削除は非同期で実行してよいが、削除済みコンテンツが検索・回答・引用に再出現してはならない。cache も削除・無効化対象に含める。
- **FR-008a**: バックアップから復元する場合は、復元後に tombstone / deletion log を必ず再適用しなければならない。

**検索・回答生成**

- **FR-009**: システムは、ユーザーの権限とメタデータフィルタを考慮して関連チャンクを検索しなければならない。検索には日本語・多言語に対応した embedding を用いる（hybrid search 採用時は日本語向け analyzer/tokenizer の利用を plan フェーズで検討する）。
- **FR-010**: 検索は、query rewrite・metadata filter・top_k・score threshold・rerank の各設定を変更可能でなければならない。
- **FR-010a**: query rewrite / HyDE / step-back prompt 等の query transformation は、低 confidence や profile 明示時など条件付きでのみ同期実行し、`max_synchronous_llm_calls` を超えてはならない。常時多段 LLM call を本番 hot path に入れてはならない。
- **FR-011**: システムは、検索結果を必要に応じてrerankし、回答生成に用いなければならない。
- **FR-011a**: rerank は bounded candidate set にのみ適用しなければならない。RetrievalProfile は `vector_top_k`、`rerank_candidate_limit`、`final_context_limit`、`max_context_tokens` を持ち、既定では retrieve 50 → rerank 20 以下 → final context 8 chunks / 8000 tokens 以下を目安にする。
- **FR-012**: システムは、検索された根拠に基づく回答を生成し、実際に引用した根拠チャンクのみを出典として返さなければならない。
- **FR-013**: 回答には、引用元・`document_id`・`chunk_id`・該当テキスト範囲・信頼度・使用チャンク一覧を含めなければならない。
- **FR-014**: 根拠が不足する場合、システムは推測で回答せず「根拠不足」を明示して返さなければならない。判定は2段階とする：
  - **(a) Retrieval pre-gate**: 権限確認済みチャンクの中に `score_threshold` を満たす候補が存在しない、または `minimum_evidence_count` を満たさない場合、回答生成せず「根拠不足」を返す。
  - **(b) Post-generation evidence check**: 回答生成後、回答内容が引用チャンクにより裏付けられているかを検証する。主要な主張が根拠チャンクで支持できない場合は、回答を返さず「根拠不足」とするか、支持できる範囲に回答を縮小する。
- **FR-014a**: `score_threshold`・`top_k`・`minimum_evidence_count`・自己評価の基準は、query profile / collection 単位で設定可能でなければならない。
- **FR-014b**: LLMによる自己評価（post-generation evidence check）は品質ゲートとして用い、セキュリティ境界として扱ってはならない。権限制御は FR-022/FR-025 のACLによってのみ保証する。

**追跡・監査・観測**

- **FR-015**: すべての検索結果・回答は、`source_id`・`document_id`・`chunk_id`・`version`・`retrieval_score` に追跡可能でなければならない。
- **FR-016**: 各処理（取り込み・索引・検索・生成・評価）は、監査ログとトレース（相関ID）を残さなければならない。
- **FR-017**: 各段階のレイテンシ・スループット・エラー率・コストはメトリクスとして公開されなければならない。
- **FR-017a**: answer request hot path は、相関IDごとに `llm_call_count`、`retrieval_ms`、`rerank_ms`、`generation_ms`、`total_ms`、`retrieved_chunks`、`rerank_input_count`、`context_tokens`、`prompt_tokens`、`completion_tokens`、`cache_hit` を記録しなければならない。
- **FR-017b**: hot path metrics は tenant/user 識別子を hash 化して保存し、raw user query・raw retrieved context・raw identity を既定で保存してはならない。LoggingPolicy の raw opt-in があっても security hard gate の対象とする。
- **FR-017c**: production readiness dashboard/eval は平均 latency だけでなく p50/p95/p99、error rate、queue time、provider rate limit、LLM call count、token count、cache hit rate を表示・比較できなければならない。

**API・管理**

- **FR-018**: システムは、ingest・search・answer・evaluate・feedback・admin の各操作をAPI経由で実行できなければならない。MVPの安定提供面は **API + SDK** とする。
- **FR-019**: 管理操作（データソース・同期スケジュール・権限・インデックス・評価設定の管理）は **admin API** として提供されなければならない。管理UIは MVP の必須範囲外とし、必要な場合でも後続フェーズの最小UIとして扱う。
- **FR-019a**: システムは、API ドキュメント（Swagger/OpenAPI 等）を提供しなければならない。MVPでは API ドキュメントと admin API を優先する。
- **FR-020**: APIはバージョン管理され、後方互換性ポリシーを持たなければならない。

**マルチテナント・セキュリティ**

- **FR-021**: システムは、**tenant を最上位のハード分離境界** とするマルチテナント分離をサポートしなければならない。collection/project は tenant 内のサブグルーピングとする。すべての document・chunk・embedding・job・evaluation・audit log・cache entry は `tenant_id` を必須で持たなければならない。検索・ACL・監査・コスト集計は tenant→collection→document の階層で評価しなければならない。
- **FR-021a**: クロステナント検索は MVP では禁止しなければならない。Vector index は tenant 単位の namespace/partition/index 分離を必須とする（実装方式は plan フェーズで決定）。
- **FR-022**: ACLは **deny by default** とし、権限のないチャンクは retrieval result・reranker input・LLM context・answer citation のいずれにも含めてはならない。権限フィルタは可能な限り検索時点で **pre-filter** し、post-filter のみに依存してはならない。
- **FR-023**: 認証・認可の判断、データアクセス、削除操作は監査ログに記録されなければならない。
- **FR-024**: システムは、取り込み時に PII/secret の検出・分類・タグ付けを行わなければならない。全コンテンツの一律 redaction は必須にしない。tenant/collection の policy に応じて、indexing前 redaction / 回答時 redaction / authorized retrieval を選択可能にしなければならない。
- **FR-024a**: ログ・トレース・プロンプト保存・評価データ・フィードバック・エラー出力には redaction/masking を必須適用しなければならない。secret と判定された値は、原則としてログ・トレース・評価データ・プロンプト履歴に保存してはならない。
- **FR-024b**: 評価データ登録時には PII/secret scrub を必須チェックとしなければならない。redaction 済みデータと原文の扱いは audit log で追跡可能にしなければならない。
- **FR-025**: 認証・認可は **ハイブリッド方式** を採る。
  - RAG基盤は tenant / app / API client の認証を行い、テナント境界とアプリ境界を強制しなければならない。
  - エンドユーザーの `user_id`・`groups`・`roles` は呼び出し側アプリが **署名付きトークン** で表明し、基盤はその claims を検証して ACLフィルタリング・監査ログ・検索/回答制御に用いなければならない。
  - MVPにおいて基盤は、エンドユーザーのログイン機能やパスワード管理を持たない。一方で **API key / client credential / signed token validation / audit log** は基盤側の責務とする。
- **FR-025a**: ACLの粒度は **tenant / project(collection) / document** を基本とし、user / group / role 単位の許可をサポートしなければならない。chunk は所属 document の ACL を継承する。

**評価・品質ゲート**

- **FR-026**: システムは、評価用の質問・期待回答・期待根拠を登録し、検索品質・回答品質・引用品質を測定できなければならない。MVP必須指標は **recall@k・citation accuracy・groundedness・p95 latency・query cost** とする。
- **FR-027**: システムは、ユーザーまたは評価ジョブによる回答へのフィードバックを、回答・引用に紐づけて保存できなければならない。
- **FR-028**: リリース候補は自動評価ゲートを通過しなければならない。検索品質・回答品質・レイテンシ・コストは初回 evaluation run で baseline を確定し、以後は baseline 比の回帰をブロックする（暫定目標値や k の具体値は plan フェーズで定義）。一方で **ACL漏洩・権限外チャンク混入・削除済み文書の再出現・テナント分離違反は baseline に関係なく absolute hard gate** とする。

**信頼性・性能**

- **FR-029**: p95レイテンシ・スループット・同時実行数・最大文書サイズ・最大チャンク数を設定可能にしなければならない。
- **FR-029a**: performance budget は QueryProfile / RetrievalProfile / runtime Settings から設定可能でなければならない。必須項目は `max_synchronous_llm_calls`、`max_context_tokens`、`max_context_chunks`、`vector_top_k`、`rerank_candidate_limit`、`final_context_limit`。
- **FR-029b**: load/performance test は average latency だけで合格としてはならない。large corpus / many tenants / long documents / high concurrency の synthetic query で p50/p95/p99、error rate、queue time、retrieval/rerank/generation breakdown を測定しなければならない。
- **FR-029c**: vector search は tenant/ACL/metadata filter pushdown と ANN / metadata index を前提に設計しなければならない。pgvector 等で index 未設定または post-filter 依存の場合は production readiness gate を fail させる。
- **FR-030**: プロバイダ障害時は、指数バックオフ付きリトライ・dead-letter queue・サーキットブレーカーを採用しなければならない。原則 **fail-closed** とし、誤った部分結果や根拠不足の回答を返してはならない。コンポーネント別の既定動作は以下とする：
  - **Parser失敗**: 対象文書を failed としてマークし失敗理由を保存、再実行可能にする。正常に解析できていない文書は検索対象にしない。
  - **Embedding失敗**: リトライ後も失敗した場合は indexing job を failed とする。embedding が存在しない chunk は vector search 対象にしない。
  - **Vector Store write失敗**: index 登録を完了扱いにしない。metadata DB と vector index の整合性を job status で追跡する。
  - **Vector Store read失敗**: 安全な fallback retrieval が構成されていない限り、回答生成を行わず一時的に回答不可と返す。
  - **Reranker失敗**: rerank なしの検索結果が score threshold と evidence requirements を満たす場合のみ回答生成に進む。満たさない場合は根拠不足または一時的に回答不可とする。
  - **LLM失敗**: 回答生成を行わず一時的に回答不可と返す。retrieval 結果だけを使って推測回答してはならない。
  - **Connector失敗**: 同期ジョブを failed として記録し再実行可能にする。既存の last successful index は維持してよいが、レスポンスに indexed_at / freshness を反映できるようにする。
- **FR-031**: 以下の **13 抽象** は差し替え可能なインターフェースで抽象化されなければならない（plan / interfaces / tasks T009 と一致）：connector / parser / OCR engine / layout(region) extractor / chunker / captioning provider / embedding provider / visual embedding provider / vector store / reranker / LLM provider / VLM provider / **task queue (job queue) provider**。AWS MVP では SQS + DLQ worker を既定 adapter とし、local/dev adapter や将来の orchestration adapter は同じ TaskQueue contract 越しに差し替える。captioning provider は optional enrichment だが同じく差し替え可能とする。

**コスト管理**

- **FR-032**: システムは、tenant 単位・collection 単位・query 単位で cost budget を設定可能にしなければならない。LLM token・embedding token・rerank・storage・indexing job のコストを記録しなければならない。
- **FR-033**: システムは、節約戦略として embedding cache / checksum による再Embedding抑制 / rerank 対象を上位N件に限定 / query profile による cheaper model・smaller top_k・rerank skip の選択 / 回答キャッシュまたは retrieval キャッシュ / budget 超過時の graceful degrade をサポートしなければならない。
- **FR-034**: graceful degrade によって根拠不足判定（FR-014）や ACL（FR-022）を弱めてはならない。安全に回答できない場合は、推測回答ではなく `budget_exceeded` または `temporarily_unavailable` を返さなければならない。

**画像・ビジュアルRAG [CR: 画像RAG]**

- **FR-035**: システムは、画像・スキャンPDF・図表を含む文書を取り込み、ページ画像/画像領域を **visual asset** として **object storage に保存** しなければならない。visual asset は `tenant_id`・所属 document・ACL・checksum・version を持ち、document のライフサイクル（差分同期・削除・再インデックス）に従う。
- **FR-036**: システムは、画像・スキャンPDF に対し **OCR** を実行し、抽出テキスト・信頼度・原画像上の領域座標（bounding box）を保持しなければならない。OCR テキストは既存のテキストチャンク経路に統合し、追跡可能（source/document/chunk/version）にする。
- **FR-037**: システムは、**layout / region 抽出**（段落・見出し・表・図・キャプション等のブロック分割）を行い、各 region に bounding box・page・種別・heading_path を付与しなければならない。
- **FR-038**: システムは、画像/region に対する **visual embedding** を生成し、検索インデックスに保存しなければならない。テキスト embedding と visual embedding は同一 retrieval 経路で扱えるようにし（マルチモーダル検索）、`embedding_model_version` を region/visual chunk に記録する。
- **FR-039**: システムは、**visual retrieval** をサポートしなければならない。テキストクエリから画像/region を検索でき、ACL pre-filter・tenant 分離・tombstone 除外をテキストと同様に適用する。権限外の visual asset / region / crop / OCR text / generated caption は結果・rerank・VLM入力・citation・thumbnail preview のいずれにも含めてはならない。
- **FR-040**: システムは、回答生成に **VLM（Vision LLM）provider** を用いて画像/region を根拠にできなければならない。VLM へ渡す画像・領域は **検索済みかつ権限確認済み** のものに限定しなければならない（FR-022 と同等）。VLM provider は差し替え可能なインターフェースで抽象化する（FR-031 を拡張）。
- **FR-041**: 回答には **visual citation** を含めなければならない。visual citation は `asset_id`・`document_id`・`page`・`bounding box`・（OCR由来があれば）引用テキスト・`retrieval_score` を持つ。引用は実際に根拠とした画像/region に限定する（FR-012 と同等）。
- **FR-042**: 画像の根拠が不足する場合（OCR/visual 検索のスコアが閾値未満、または VLM が画像で主張を裏付けられない）、推測せず「根拠不足」を返さなければならない（FR-014 の2段階ゲートを visual citation に適用）。
- **FR-043**: システムは、取り込み時に **画像内 PII/secret**（顔・署名・身分証・カード番号等）を検出・分類・タグ付けし、policy に従って indexing前 / 回答時の領域マスク（redaction）または authorized retrieval を選択可能にしなければならない（FR-024 を画像に拡張）。画像・EXIF・OCRテキスト・generated caption・thumbnail・crop すべてに同一の PII/secret 方針を適用する。ログ・トレース・プロンプト保存・評価データには原画像/未マスク領域を残してはならない。
- **FR-043a**: システムは、画像取り込み時に **EXIF metadata を検査**しなければならない。GPS・端末情報・撮影時刻など PII/機密になり得る metadata は policy に従って strip / mask / retain を制御する。**デフォルトでは GPS 等の高リスク EXIF を保存しない**。EXIF 由来情報を保存する場合は tenant/collection policy と audit log の対象とする。
- **FR-044**: システムは、画像処理のコストを **独立して計測可能** な項目として記録し、tenant/collection/job/query 単位の budget に算入しなければならない：**OCR cost / layout extraction cost / captioning cost / visual embedding cost / VLM image token cost / thumbnail・crop generation cost / visual storage cost**。`VLM image token cost` は VLM 推論コストの総称に含めず独立計測する。節約戦略として OCR/embedding/caption 結果の checksum キャッシュ・解像度/ページ上限・region 上位N件限定・cheaper VLM 選択・captioning の有効/無効を query profile / ingestion option で選べるようにする（FR-032/033 を拡張）。
- **FR-045**: 削除は document / visual asset / layout region / crop / OCR text / generated caption / visual embedding / thumbnail を含めてカスケード無効化しなければならない。あわせて関連する **retrieval cache・answer cache・VLM response cache・visual answer cache・thumbnail cache・crop cache** を無効化する。tombstone 後に検索・回答・visual citation・VLM入力・thumbnail preview へ再出現してはならず、削除済み visual artifact を含む cached answer を再利用してはならない（FR-008 を画像に拡張）。

**captioning [CR: optional enrichment]**

- **FR-046**: システムは、画像 / PDFページ画像 / 文書内画像 / layout region に対し **captioning**（自動キャプション生成）を実行できなければならない。captioning は **optional enrichment** であり、全画像への必須実行ではない。
- **FR-047**: captioning は tenant / collection / ingestion job 単位で enable / disable でき、cost budget によっても制御できなければならない。
- **FR-048**: captioning 結果（`generated_caption_text`）は **検索補助** に利用できるが、画像内容に関する回答の **一次根拠としては扱ってはならない**。一次根拠は元画像 / page image / crop / visual region / OCR region とする。caption のみで回答を裏付けられない場合は VLM が元画像または crop を確認しなければならない。caption が不確実・曖昧・画像と矛盾する場合は推測回答をしてはならない。
- **FR-049**: `generated_caption_text` には PII/secret detection と redaction/masking policy を適用しなければならない（FR-043 と同等）。
- **FR-050**: captioning 失敗時は ingestion 全体を failed にしなくてよい。ただし `caption_status=failed` と理由を記録し、再実行可能にしなければならない。
- **FR-051**: captioning のコストは tenant / collection / job / query 単位で記録しなければならない（FR-044 の captioning cost）。
- **FR-052** [CR:画像 crop]: **crop** は VisualAsset または LayoutRegion から生成される derived artifact とし、元の `tenant_id`・`collection_id`・ACL・redaction policy・deletion policy を継承しなければならない。権限のない crop は retrieval result・reranker input・VLM context・citation・thumbnail preview に含めてはならない。元 asset/region が削除/tombstone された場合、関連 crop も検索・回答・表示・cache から即時除外する。

### Key Entities *(include if feature involves data)*

- **Tenant / Project(Collection)**: データ分離の境界。所属する DataSource・Document・評価設定・ACL のスコープを定める。ACL粒度の基本単位（tenant / project(collection) / document）。
- **Identity Claims**: 呼び出しアプリが署名付きトークンで表明する `user_id`・`groups`・`roles`。基盤が検証し、ACLフィルタ・監査・検索/回答制御に用いる（基盤はパスワード/ログインを管理しない）。
- **QueryProfile**: 検索・回答の挙動設定。`score_threshold`・`top_k`・`minimum_evidence_count`・rerank・query rewrite・自己評価基準に加え、`max_synchronous_llm_calls`・`max_context_tokens`・`max_context_chunks` を保持し、collection 単位で設定可能。
- **DataSource**: 取り込み元の定義（アップロード、ローカル/オブジェクトストレージ、将来の外部ソース）。同期スケジュールを持つ。
- **Document**: `tenant_id`・`source_id`・`document_id`・`version`・`checksum`・`metadata`・`ACL`・`created_at`・`updated_at`・`indexed_at`・`tombstone`(削除状態) を持つ取り込み単位。
- **Chunk**: `tenant_id`・`chunk_id`・`document_id`・`text`・`token_count`・`position`・`heading_path`・`metadata`・`embedding_model_version`・原文との offset mapping を持つ検索単位。`modality`（text | visual）を持ち、document の ACL を継承する。
- **VisualAsset** [CR:画像]: `tenant_id`・`asset_id`・`document_id`・`page`・object storage 上の保存先・`checksum`・`version`・`metadata`・ACL（document継承）・`tombstone` を持つページ画像/画像。
- **LayoutRegion** [CR:画像]: `tenant_id`・`region_id`・`asset_id`・`document_id`・`page`・`bounding_box`・`type`（text/figure/table/chart/screenshot/form/caption）・`heading_path`・OCRテキスト・`ocr_confidence`・`pii_tags`・`visual_embedding`・`embedding_model_version` を持つ。visual chunk の正本として retrieval 対象。captioning（optional）有効時は `generated_caption_text`・`caption_model`・`caption_status`（not_requested|pending|succeeded|failed|skipped）・`caption_confidence`(任意)・`caption_generated_at`・`caption_redaction_status`・`caption_error_reason`(任意) を持つ。`region_type=caption` と `generated_caption_text` は区別する。
- **Embedding（canonical）** [CR]: 独立した MultimodalEmbedding エンティティは作らず、embedding に `modality`（text|visual）と `target_type`（text_chunk | visual_asset | layout_region | ocr_text | generated_caption）を持たせて表現する。
- **IngestionJob**: 取り込みジョブ。状態・失敗理由・対象文書・再実行履歴を持つ。
- **Query / Answer**: ユーザーの質問と、根拠付き回答・引用・信頼度・使用チャンク一覧。
- **Citation**: 回答が参照した根拠。`kind`（text|visual）を持つ。text: `document_id`・`chunk_id`・該当テキスト範囲（原文上の code point / grapheme cluster オフセット）・`retrieval_score`。[CR:画像] visual citation（VisualCitation 別エンティティは作らず Citation(kind=visual) として扱う）は `image_id`/`asset_id`・`page_number`・`region_id`・`bbox`・`crop_uri`・（OCR由来の）引用テキスト・`retrieval_score` を持つ。
- **CostRecord / Budget**: tenant/collection/query 単位のコスト記録と上限。LLM token・embedding token・rerank・storage・indexing job のコストを集計する。
- **EvaluationSet / EvaluationRun**: 評価用の質問・期待回答・期待根拠と、その実行結果（recall@k・citation accuracy・groundedness・レイテンシ・コスト）。
- **Feedback**: 回答に紐づくユーザー/評価ジョブからの品質フィードバック。
- **AuditLog / Trace**: 各段階の監査記録と相関IDによる横断トレース。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 品質ゲートは **2系統** で構成する。
  - **検索・生成品質（baseline relative gate）**: 初回 evaluation run で baseline を確定し、以後のリリースでは recall@k・citation accuracy・groundedness・latency・cost について baseline 比の回帰をブロックする。初期段階では絶対閾値を hard gate にしない（暫定目標値は plan フェーズで定義）。評価データセットが十分な件数に達した後、baseline relative gate に加えて absolute threshold を導入できる設計とする。
  - **セキュリティ・データ整合（absolute hard gate, zero-tolerance）**: ACL漏洩、削除済み文書の再出現、権限外チャンクのLLM投入は、baseline に関係なく常に hard fail とする（SC-002〜SC-004, SC-007 を参照）。[CR:画像] さらに visual asset / crop / OCR text / generated caption における ACL漏洩、削除済み visual artifact の再出現、テナント分離違反も absolute hard gate とする（SC-009 を参照）。
- **SC-002**: 根拠が存在しない質問に対して、推測回答ではなく「根拠不足」を返す割合が 100% である（評価データセット中の「回答不能」設問で誤った断定回答が 0 件）。
- **SC-003**: 削除された文書が、削除完了後の検索結果・回答・引用に再出現する件数が 0 である（**absolute hard gate**：baseline に関係なく hard fail）。
- **SC-004**: 権限のないユーザーに対し、制限文書の内容・存在が検索結果・回答・引用から漏洩する件数が 0 である。
- **SC-005**: 取り込み・検索・回答生成の各リクエストが、相関IDにより端から端まで欠落なくトレースできる（トレース取得率 100%）。
- **SC-006**: 品質回帰（recall@k・citation accuracy・groundedness のいずれかがベースライン比で有意に低下）が検出された候補は、100% リリースがブロックされる。
- **SC-007**: ソース側で更新された文書が、差分同期後に旧バージョンの内容を検索・回答に残さない（旧バージョン残存 0 件）。
- **SC-008** [CR:画像]: 画像系の評価指標が baseline 比で回帰しない（baseline relative gate）。MVP の visual 指標は以下とする：
  - **visual_recall@k**: 正しい image/page/region が検索上位 k 件に含まれる割合。
  - **visual_citation_accuracy**: 回答の visual citation が正しい image/page/region を指す割合。
  - **bbox_iou**: 期待 bbox と引用 bbox の重なり（IoU）が十分である度合い。
  - **visual_groundedness**: 画像由来の回答主張が、引用された元画像/crop/visual region で支持される度合い。
  - **p95 visual answer latency**: 画像を含む answer API の p95 レイテンシ。
  - **visual query cost**: OCR・captioning・visual embedding・VLM image token を含む query コスト。
- **SC-009** [CR:画像]: 権限のない visual asset / crop / OCR text / generated caption / region が検索結果・回答・visual citation・VLM入力・thumbnail preview に出現する件数が 0、削除済み visual artifact が再出現する件数が 0、テナント分離違反が 0 である（**absolute hard gate**：baseline に関係なく hard fail）。

## Assumptions

- 取り込みフォーマットのMVP対象は PDF・Markdown・HTML・プレーンテキストとし、日本語文書を対象に含める。Slack・Confluence 等の外部SaaSコネクタは将来拡張とする（非ゴール）。
- 管理UIは MVP の必須範囲外（非ゴール）。MVPの安定提供面は API + SDK + admin API + API ドキュメント（Swagger/OpenAPI 等）とする。
- 独自LLMの学習基盤は構築せず、既存の Embedding / LLM プロバイダをインターフェース経由で利用する（非ゴール）。
- [CR:画像] 画像・スキャンPDF・図表を含む文書（静止画・文書画像・ページ画像）はRAG対象に含める。OCR・layout抽出・captioning・visual embedding・VLM provider はインターフェース越しに利用し差し替え可能とする。captioning は **optional enrichment**（検索補助）であり、全画像必須実行ではなく tenant/collection/ingestion option/budget で制御。画像回答の一次根拠は元画像/page image/crop/visual region/OCR region とし、caption は一次根拠にしない。
- リアルタイム音声・動画RAGは引き続きMVP対象外（非ゴール）。人間レビューなしの高リスク（法務・医療・金融）判断の自動化も対象外（非ゴール）。
- 性能目標（p95レイテンシ・スループット・同時実行・最大文書サイズ・最大チャンク数）は、固定値ではなく設定可能なパラメータとして提供し、初期既定値は運用環境に合わせて設定する。
- データ保持・バックアップ世代は、業界標準的な既定値を用い、テナント単位で調整可能とする。
- 評価のベースラインは、初回リリース時のスコアを基準として確立し、以後の候補と比較する。
