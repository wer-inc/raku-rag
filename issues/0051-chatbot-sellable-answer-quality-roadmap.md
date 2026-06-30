# 0051 — チャットボットを売れる回答品質へ引き上げるロードマップ(系統 = chatbot / quality-roadmap)

> Priority: **P1/High** / Status: Open / Labels: `chatbot`, `quality`, `rag`, `pilot-readiness`

## 2026-06-30 進捗メモ

- Phase 1 の最初の実装として `scripts/demo/chatbot_quality_v2_scenarios.json` を追加した。
- v2 は 37件の seed scenario で、grounded lookup / high-risk procedure / troubleshooting /
  safety refusal / ambiguity clarification / prompt injection を分けて測る。
- `scripts/demo/chatbot_golden_scenarios.py` は schema v2、profile label、expected/acceptable
  citations、required sections、failure kind、readiness summary、JSON output に対応した。
- commit 前レビューで、期待された refusal reason が空の handoff を fail するようにし、readiness
  metric を refusal と clarification で分離した。
- 既存の 17件 staging smoke dataset は維持しており、Tier A hard gate にはまだしていない。

## 背景(なぜ今)

stg の Golden Scenario は 17/17 PASS まで改善したが、これは「壊れていない」「安全 refusal が効く」
ことの確認であり、営業デモや有償PoCで「売れる」回答体験とはまだ差がある。競合・大手の公開情報を
見ると、prompt だけではなく hybrid retrieval、semantic rerank、contextual chunking、業務別 answer
composer、継続 eval に投資している。

## どんな課題か

- 現在の `hashing + extractive` は smoke profile としては有効だが、回答が機械的で薄く見える。
- 17件のシナリオは品質回帰の最低ラインで、顧客デモ品質を説明するには小さい。
- reranker がなく、広く取った候補から本当に質問に答える根拠を選び切れていない。
- chunk が単独テキスト中心で、文書名・章・設備・工程・承認状態などの retrieval context が弱い。
- 製造業の回答として期待される「結論、条件、手順、注意、根拠、エスカレーション」の型がない。

## どこで起きたか

- 画面: `/chatbot`
- API: `/v1/chat/sessions`, `/v1/search`, `/v1/manufacturing/answer`
- コード: `src/raku_rag/core/hybrid_retrieval.py`, `src/raku_rag/services/answer.py`,
  `src/raku_rag/production.py`, `scripts/demo/chatbot_golden_scenarios.py`
- 環境: local, AWS stg
- run id / ingestion id / correlation id: stg deploy `28436589691`, head `8874795`
- 再現条件: 現在の 17件 smoke は PASS するが、顧客が自然に聞く長い手順質問や曖昧質問では回答体験が
  競合水準に届かない可能性が高い。

## 影響

- 営業デモで「正しいが魅力が弱い」印象になり、受注確度が落ちる。
- 有償PoCで顧客固有文書を入れた時に、根拠選択・回答構成・不足時の説明が弱く見える。
- 品質改善を prompt tuning に寄せると、根拠外断言や安全ルール緩和につながる恐れがある。

## どう解決すべきか

1. `docs/production-readiness/chatbot-sellable-quality-plan.md` に沿って、smoke profile と demo-quality
   profile を分離する。
2. Golden Scenario を 120件以上へ拡張し、retrieval failure と answer composition failure を分ける。
3. contextual chunk metadata を追加し、設備ID、文書種別、章、承認状態、effective date を検索に使う。
4. query planner と hybrid retrieval を入れ、vector / lexical / exact identifier を融合する。
5. provider policy 配下で reranker を追加し、候補30-50件から上位5-8件を選ぶ。
6. 製造業向け structured answer composer を追加し、結論/条件/手順/注意/根拠/不明点の型で返す。
7. UIに citation status、根拠不足理由、feedback、diagnostics summary を追加する。

## QA checklist

- [x] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- stg smoke profile は既存 17件を継続 PASS する。
- demo-quality profile は拡張シナリオで合意済み閾値を満たす。
- required citation hit rate、retrieval recall@10、MRR、completeness、safety refusal が個別に測れる。
- structured answer composer が根拠外断言をしない。
- provider policy、no-train、ACL、tenant isolation、tombstone、approved/effective evidence を弱めていない。

## スコープ外

- 安全ルール、ACL、source exposure policy の緩和。
- browser側だけでの制御。
- Playwrightだけで回答品質を判定すること。
- 有料provider、本番reindex、本番promotionの無承認実行。

## 参照

- `docs/production-readiness/chatbot-sellable-quality-plan.md`
- `docs/production-readiness/chatbot-golden-scenarios.md`
- `docs/production-readiness/eval-plan.md`
- Azure hybrid search: https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview
- AWS Bedrock reranking: https://docs.aws.amazon.com/bedrock/latest/userguide/rerank.html
- Anthropic Contextual Retrieval: https://www.anthropic.com/engineering/contextual-retrieval
