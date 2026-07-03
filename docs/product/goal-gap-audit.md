# 製品化ギャップ棚卸し — 新goal.md(販売品質RAG改善プラン)vs 実装(★G, 2026-07-03)

goal.md が「業務ナレッジRAGの製品化改善プラン」(評価基盤・検索品質・運用監視・改善ループ)に
更新されたことを受け、プラン全項目を develop @ 850d3fc に対して棚卸しした。
判定: **A=実装済み** / **B=部分実装** / **C=未実装**。

## サマリ

goal §8 優先順位のうち骨格は既に立っている — ACL/tenant の検索前段強制(§8-7)、CI回帰
ゲート(§8-8)、reranker(§8-6)、evidence-only prompt + no-answer(§8-2/3)、出典
metadata+引用UI は A。残るギャップは4クラスタに集中する:

1. **trace永続化と失敗分類**(goal の「最初の一手」そのもの)— per-query トレースが揮発
2. **評価ゲートの穴** — 回答不能/矛盾/越境カテゴリがCIコーパスに無い、意味的品質指標なし
3. **コスト/性能制御** — キャッシュ・モデルルーティング・実測p95が無い
4. **文書鮮度・版管理** — owner/review期限なし、最新版選択・矛盾検知なし

## 判定一覧

### Retrieval / Context(goal §1-1, §1-3)

| 項目 | 判定 | 根拠 | 備考 |
|---|---|---|---|
| 構造チャンク+メタデータ | **B** | providers/chunkers.py:39, services/ingestion.py:41 | 文種別プロファイル・heading_path・offset有り。テキストチャンクのpage番号・親子チャンク無し |
| ハイブリッド検索(BM25+vector) | **A** | services/retrieval.py:105, core/hybrid_retrieval.py:98 | 3レグ統合(vector/識別子/lexical+CJK bigram)。融合はunion-max(RRFではない) |
| reranker | **A** | providers/rerankers.py:26 | production時 Bedrock Cohere rerank-v3-5、fail-safe降格 |
| query rewrite | **B** | chatbot/coreference.py, core/query_planner.py:90 | 照応解決・識別子抽出有り。同義語/略語展開・HyDE無し(tenant_lexiconは検索展開に未接続) |
| メタデータ検索条件 | **B** | persistence/postgres.py:535-620 | SQL条件は tenant/tombstone のみ。ACLはPython後段(:549)、doc_type/effective等はboost/後段フィルタ |
| dedupe/diversity/packing | **B** | services/retrieval.py:91, services/answer.py:936 | 広取り→絞り・トークン上限有り。doc単位dedupe・MMR・重要根拠先頭配置無し |

### Data / ライフサイクル(goal §1-4)

| 項目 | 判定 | 根拠 | 備考 |
|---|---|---|---|
| 文書ライフサイクル | **B** | manufacturing/domain/metadata.py:30, safety/gate.py:157 | 製造overlayは完備(draft/approved/obsolete+effective窓)。ただし検索フィルタでなく回答時ゲート — draft/obsoleteも検索には載る。base層はtombstone+versionのみ |
| 最新版選択・矛盾検知 | **C** | ingestion/approval.py:167 | supersede は手動運用。自動の版比較・canonical解決・矛盾クラスタリング・レビューキュー無し |
| owner/review_cycle/鮮度警告 | **C** | (全域grep hit無し) | フィールド自体が無い。stale警告は obsolete 由来のKPIのみ |
| 取込品質(parse QA/OCR/表) | **B** | workers/ingestion.py:529, services/structured_tables.py | OCRゲート(★V1)・表抽出・失敗検知有り。テキスト引用にpage番号が乗らない(visualのみ) |
| チャンク単位ACL | **C** | core/security/acl.py:52 | 文書単位のみ(ScopeType=tenant/collection/document) |

### Generation / Security(goal §1-2, §4-2, §4-3)

| 項目 | 判定 | 根拠 | 備考 |
|---|---|---|---|
| evidence-only prompt | **A** | providers/llms.py:270-283 | bedrock/openai/gemini共通 grounded/v1。data-not-instructions明示 |
| no-answerゲート | **B** | services/groundedness.py:76, services/answer.py:163-588 | 多段fail-closed(予算/pre_gate/引用再検証/post_check)。ただし決定的term-overlapのみ — claim単位検証(claim_check)はJP誤検知理由でopt-in・本番経路外 |
| claim単位引用 | **B** | services/answer.py:483-586 | チャンク単位+数値アンカー(#56)。claim→span対応・text_rangeは全チャンク |
| 回答タイプ別テンプレ | **C** | services/answer_format.py | 汎用1種(grounded-answer-display-v1)のみ |
| 版矛盾の明示回答 | **C** | safety/gate.py:157, api/answer_ext.py:813 | 抑制(obsolete降格+旧版警告)のみ。「A文書では〜/B文書では〜/最新は〜」の統合回答無し |
| インジェクション防御 | **B** | services/injection.py:91, services/answer.py:278-311 | 回答時中和+出力guardrail+ゼロ幅対策(007)。取込時の命令文走査・異常チャンク検知無し |
| tenant注入/ACL/PII/監査 | **A** | answer.controller.ts:16, observability/redaction.py:13, manufacturing/domain/audit.py:189 | サーバ側tenant注入・ACL前段+再assert・Redactor(取込/監査/ログ/電話)・ハッシュ連鎖監査+エビデンスパック(★1) |
| AI出力と実行の分離 | **A** | drafts/generator.py, chatbot/authority.py | draft-by-default・人間承認必須。L4は意図的に未配線 |

### Evaluation(goal §2)

| 項目 | 判定 | 根拠 | 備考 |
|---|---|---|---|
| 評価セット階層 | **B** | tests/fixtures/uat/golden_corpus.json, scripts/demo/chatbot_quality_v2_*.json | smoke〜release-gate(18問)〜high-risk(19問)〜40問+135問拡張(SME待ち)。本番failure由来セット無し |
| QAスキーマ | **B** | eval/models.py:34, chatbot_quality_v2_scenarios.json | required/forbidden_terms・expected_behavior はstagingシナリオ側のみ。CIゲート側に risk_level/persona/reference_answer 無し |
| カテゴリ網羅 | **B** | eval/probes.py:155,177 | 回答不能・矛盾・越境が**CIゲートコーパスに入っていない**(staging/probe散在)。同義語スライス・最新版選択(2つの有効版から新を選ぶ)無し |
| 自動指標 | **B** | eval/runner.py:212-229 | recall/precision/MRR/citation_accuracy/groundedness/p95/cost 有り。answer correctness/relevance・refusal-accuracy・nDCG・context precision 無し |
| LLM-as-judge | **C** | eval-plan.md:38(明示defer) | 決定的token-overlapのみ。生成型の「もっともらしい嘘」はゲートを通過し得る |
| リグレッションゲート | **B** | .github/workflows/ci.yml:62-84 | blocking eval-gate有り(閾値+version registry)。変更種別→評価マトリクス無し、40/135問シナリオはCI外 |
| risk-weighted score | **C** | — | 高リスクはhard floor(refusal 100%)のみ、加重合成スコア無し |

### Ops / Product(goal §2-5, §3, §4-1)

| 項目 | 判定 | 根拠 | 備考 |
|---|---|---|---|
| per-queryトレース永続化 | **C** | observability/metrics.py:57(in-memory), 0002 migration | rewritten_query・chunkスコア・rerankスコア・model・トークン・段階別latency・failure_typeが揮発。**cost_records / rerank_traces テーブルはRLS付きで存在するが writer が無い**。過去クエリの再構成不能 |
| 実測p50/p95・cost/query | **B** | metrics.py:210, kpi/poc_metrics.py:139-142 | in-memoryのみ。KPI画面のp95は evidence-count 代理値(実latencyでない) |
| モデルルーティング/分類分岐 | **C** | core/config.py:77 | グローバルenvスイッチ(answer_llm)のみ。小型rewrite/大型高リスクの分岐無し |
| キャッシュ | **C** | services/cache.py | invalidationのみ配線、格納側ゼロ(semantic/query-result/embedding いずれも) |
| rate limit/quota/timeout | **B** | chat.controller.ts:143, services/answer.py:162 | チャットwidget RPM+テナントコスト予算のみ。回答経路のtimeout/fallback無し |
| 引用UI/信頼シグナル | **B** | CitationViewer.tsx:29-227 | page/crop/発効日/旧版警告/承認バッジは完備。最終確認日・「最新版です」肯定表示無し |
| 確認質問/フォローアップ | **B** | chatbot/agent.py:100-101 | 聞き返しsurface無し(コード内に明示ギャップ記載)。固定quick-replyのみ |
| フィードバック | **B** | FullSaasScreen.tsx:633, server.py:682-698 | UI(👍/👎+理由6分類)完備。**格納が in-memory + localStorage**、一覧APIなし — 改善ループが揮発 |
| 未回答/低評価/ナレッジ穴分析 | **B** | kpi/poc_metrics.py:86, api/dashboard.py:47 | 件数KPIのみ。質問単位ドリル・自動クラスタ無し。ナレッジ穴は電話QAの手動入力 |
| テナント利用量/課金 | **C** | FullSaasScreen.tsx:9432(MOCK_BILLING) | cost_records 未書込みのため実データ無し |
| チケット連携 | **C** | improvement-queue.ts | 内部キューのみ(GitHub/Jira連携無し) |

## 発見した実バグ

1. **high_risk_recall が常に0表示** — scripts/demo/quality_scorecard.sh:37 と
   apps/web/lib/api-client.ts:529 は `metrics.high_risk_recall` を読むが、eval runner
   (eval/runner.py:212-229)はそのキーを metrics に emit しない(security_checks 側のみ)。
   品質・KPI画面のヘッドライン数値が恒常的に0。
2. **★V2 ③文言が未配線** — `messages.chat` / `messages.phone` は EDITABLE_NAMESPACES に
   あり書き込めるが、読む側が無く転送アナウンス等は固定文言のまま
   (industry-config-audit.md の実装順③が残)。

## 優先順位(提案 — goal §8 の順序を実装状況で補正)

| # | 項目 | 根拠 |
|---|---|---|
| **★G1** | **per-query trace 永続化 + 失敗分類** — cost_records/rerank_traces の writer + クエリトレース(rewritten_query・chunkスコア・段階latency・トークン・failure_type、Redaction方針準拠) | goal「最初の一手」。未回答分析・実p95・cost/query・本番failure評価セットすべての前提 |
| **★G2** | **評価ゲート補強** — 回答不能/矛盾/越境/最新版選択をCIコーパスへ、refusal-accuracy 指標、risk-weighted score、high_risk_recall バグ修正 | 販売判定ライン(goal §2-4)の実効化 |
| **★G3** | **フィードバック永続化 + 未回答ドリルダウン** — in-memory→PG、一覧API、質問単位分析 | 改善ループの土台(goal §3-2) |
| **★G4** | **文書鮮度** — owner/review期限/last_verified_at + stale警告 + 最新版選択 | goal §1-4「文書ライフサイクル管理はプロダクト機能」 |
| **★G5** | キャッシュ+モデルルーティング+実測レイテンシ/コスト | 粗利/SLA(goal §4-1) |
| 小粒 | ★V2③文言配線 / 確認質問surface / doc単位dedupe+MMR / テキスト引用のpage番号 | 随時挟む |

## 実装状況

- [x] 本棚卸しドキュメント
- [x] ★G1 trace永続化(query_traces 0022 + cost_records/rerank_traces writer — PR #61)
- [x] ★G3a フィードバック永続化(answer_feedback 0023 + `GET /v1/feedback` — PR #66)
- [x] ★G3b 未回答ドリルダウン(query_traces.query_redacted 0024 — 質問文はRedactorでPIIマスク後に
      保存 — + `GET /v1/quality/operational` + 品質・KPI画面「実測運用メトリクス」カード/未回答クエリ一覧)
- [x] ★G5(実測メトリクス部分)実測 p50/p95(ms)・status別件数・未回答率・低評価件数を query_traces/
      answer_feedback から集計して品質・KPI画面へ(KPI p95 の evidence-count 代理値は実測があれば置換、
      無ければ「代理値」明記)
- [ ] ★G5(残り)キャッシュ格納側+モデルルーティング(小型rewrite/高リスク大型の分岐)は未着手
- [ ] ★G2 / ★G4
