<!--
SYNC IMPACT REPORT
==================
Version change: (none) → 1.0.0
Bump rationale: Initial ratification of the project constitution (MAJOR baseline).

Principles defined (8):
  I.   Groundedness First
  II.  Traceability
  III. Security by Design
  IV.  Pluggable Architecture
  V.   Evaluation-Gated Delivery
  VI.  Observable by Default
  VII. API First
  VIII.Data Lifecycle Complete

Added sections:
  - Core Principles (8 principles)
  - Engineering Constraints
  - Development Workflow & Quality Gates
  - Governance

Removed sections: none (initial version)

Templates reviewed for consistency:
  ✅ .specify/templates/plan-template.md   — "Constitution Check" gate reads principles
                                             dynamically; no edits required.
  ✅ .specify/templates/spec-template.md   — mandatory sections (Requirements, User
                                             Scenarios) are principle-agnostic; aligned.
  ✅ .specify/templates/tasks-template.md  — task categories are generic; observability,
                                             security, and evaluation tasks map cleanly to
                                             Principles V/VI/III; no edits required.

Deferred TODOs: none.
-->

# raku-rag Constitution

このプロジェクトは、複数のアプリケーションから利用できる汎用RAG（Retrieval-Augmented
Generation）基盤を構築する。本憲章は、設計・実装・リリースにおける非交渉的（non-negotiable）な
原則を定義する。

## Core Principles

### I. Groundedness First

回答の流暢さよりも、検索された根拠に基づくことを常に優先する。

- 生成される回答は、retrieval で取得したコンテキストに裏付けられていなければならない（MUST）。
- 根拠が不足する、または矛盾する場合、システムは推測で補ってはならない（MUST NOT）。不足を
  明示し、回答不能であることをユーザーに返さなければならない（MUST）。
- 流暢さ・網羅性の向上を理由に、根拠のない主張を生成することは禁止する（MUST NOT）。

**Rationale**: RAG基盤の存在意義は信頼できる回答にある。ハルシネーションは流暢さの不足より
深刻な障害であり、根拠提示能力こそが汎用基盤としての価値を決める。

### II. Traceability

すべての回答は、その根拠まで機械的に追跡可能でなければならない。

- 回答に用いた各エビデンスは、`source_id`、`document_id`、`chunk_id`、`version`、
  `retrieval_score` を保持しなければならない（MUST）。
- これらの識別子は API レスポンスを通じて呼び出し側アプリへ公開されなければならない（MUST）。
- 追跡情報を持たない回答経路を本番に出してはならない（MUST NOT）。

**Rationale**: 監査・デバッグ・品質評価・コンプライアンスのすべてが追跡可能性に依存する。
後付けでは保証できないため、初期設計のデータモデルに組み込む。

### III. Security by Design

マルチテナント分離、アクセス制御、監査、データ削除、秘密情報の取り扱いは、初期設計に
含めなければならない（MUST）。後付けのセキュリティは認めない（MUST NOT）。

- すべての retrieval / generation はテナント境界と ACL を強制しなければならない（MUST）。
- 認証・認可の判断、データアクセス、削除操作は監査ログに記録しなければならない（MUST）。
- 秘密情報（API キー、資格情報、PII）はログ・トレース・回答に漏洩してはならない（MUST NOT）。
- データ削除要求は、インデックスとバックアップを含めて完全に履行できなければならない（MUST）。

**Rationale**: 複数アプリが共有する基盤では、1テナントの侵害が全体に波及する。分離と監査は
基盤の前提条件であり、機能ではない。

### IV. Pluggable Architecture

connector、parser、chunker、embedding provider、vector store、reranker、LLM provider は
安定したインターフェースで抽象化し、差し替え可能でなければならない（MUST）。

- 各コンポーネントは明示的なインターフェース契約を持たなければならない（MUST）。
- 上位レイヤーは具体実装（特定のベクタDB、特定のLLMベンダー等）に直接依存してはならない
  （MUST NOT）。依存はインターフェース経由とする。
- 新しい provider の追加は、既存利用側コードの変更なしに可能でなければならない（SHOULD）。

**Rationale**: 汎用基盤は技術選択の変化（モデル更新、ベクタDB移行、コスト最適化）に耐える
必要がある。差し替え可能性が長期の保守性とベンダーロックイン回避を担保する。

### V. Evaluation-Gated Delivery

検索品質、回答品質、引用品質、レイテンシ、コストの評価を自動化し、回帰があればリリースしては
ならない（MUST NOT）。

- リリース候補は自動評価スイートを通過しなければならない（MUST）。
- 評価指標（retrieval の recall/precision、回答の正確性、引用の妥当性、p95 レイテンシ、
  クエリあたりコスト）はベースラインに対して測定されなければならない（MUST）。
- 統計的に有意な回帰が検出された場合、リリースをブロックしなければならない（MUST）。

**Rationale**: RAG の品質は静かに劣化する（モデル更新、データ変化、プロンプト改変）。
評価ゲートがなければ劣化を出荷してしまう。

### VI. Observable by Default

ingestion、indexing、retrieval、generation、evaluation の各段階で、ログ・メトリクス・
トレースを取得しなければならない（MUST）。

- 各段階は構造化ログを出力しなければならない（MUST）。
- リクエストは段階をまたいでトレース可能でなければならない（相関ID等）（MUST）。
- レイテンシ、スループット、エラー率、コストはメトリクスとして公開されなければならない（MUST）。

**Rationale**: 観測性なしに Principle V（評価）と運用は成立しない。可観測性は事後追加が困難で
あり、各段階の実装時に組み込む。

### VII. API First

UI よりも先に、外部アプリから使える API、SDK、管理 API を安定化しなければならない（MUST）。

- 機能はまず API として設計・公開されなければならない（MUST）。UI は API の消費者に過ぎない。
- API は明示的にバージョン管理され、後方互換性ポリシーを持たなければならない（MUST）。
- 管理操作（テナント管理、再インデックス、削除等）も API として提供されなければならない（MUST）。

**Rationale**: 本基盤の利用者は複数アプリケーションである。安定した契約面が API であり、
UI 都合で内部設計を歪めてはならない。

### VIII. Data Lifecycle Complete

データの作成、更新、差分同期、削除、再インデックス、バックアップ、ロールバックは、すべて
設計に含めなければならない（MUST）。

- ライフサイクルの各操作（特に差分同期と削除）は明示的に設計・実装されなければならない（MUST）。
- 再インデックスとロールバックは、サービス継続性を保ちながら実行可能でなければならない（SHOULD）。
- バックアップから一貫性のある状態を復元できなければならない（MUST）。

**Rationale**: 取り込みだけを考えた RAG は運用で破綻する。差分同期・削除・再インデックスは
ソースデータが変化する現実において必須であり、初期設計から扱う。

## Engineering Constraints

- すべてのコンポーネント間の結合は Principle IV のインターフェースを介する。具体実装への直接
  依存を導入する変更は、Complexity Tracking での正当化を要する。
- 追跡識別子（Principle II）と監査・観測フィールド（Principle III/VI）は、共有データモデルの
  一部として定義され、各段階を通じて伝播されなければならない。
- 外部公開される契約（Principle VII の API/SDK）の破壊的変更は、バージョン bump と移行計画を
  伴わなければならない。

## Development Workflow & Quality Gates

- すべての feature は spec → plan → tasks → implement のフローに従う。
- Plan 段階の "Constitution Check" は本憲章の各原則に対する適合を確認する。違反は
  Complexity Tracking で正当化されない限りブロックされる。
- リリースは Principle V の自動評価ゲートを通過しなければならない。回帰はリリースをブロックする。
- コードレビューは、該当する原則（特に Groundedness、Traceability、Security、Observability）
  への適合を検証しなければならない。

## Governance

- 本憲章はプロジェクトの他のあらゆる慣行に優先する（supersedes）。
- 改正には、変更内容の文書化、レビュー承認、影響を受けるテンプレート・コードへの移行計画が
  必要である。
- バージョニングは semantic versioning に従う:
  - **MAJOR**: 原則の削除・後方非互換な再定義、ガバナンスの非互換変更。
  - **MINOR**: 新しい原則／セクションの追加、ガイダンスの実質的拡張。
  - **PATCH**: 文言の明確化・誤記修正など、意味を変えない調整。
- すべての PR / レビューは本憲章への適合を確認しなければならない。複雑性の導入は正当化を要する。
- 実行時の開発ガイダンスは `CLAUDE.md` を参照する。

**Version**: 1.0.0 | **Ratified**: 2026-06-18 | **Last Amended**: 2026-06-18
