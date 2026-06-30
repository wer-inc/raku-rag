# 0055 — ChatBot回答を結論/手順/注意/根拠の型で構造化する(系統 = chatbot / answer-composition)

> Priority: **P1/High** / Status: In progress / Labels: `chatbot`, `answer-composer`, `rag-quality`, `manufacturing`

## 実装メモ(2026-06-30)

- ChatBot の answerable な RAG回答に、表示用の固定フォーマットを追加した。
- 構造は `結論`, `条件`, `手順`, `注意点`, `根拠`, `不明点`。
- 元のRAG回答本文は `結論` に保持し、`条件` と `根拠` は collection/citation metadata から作る。
- `手順` と `注意点` は回答本文内の関連文だけを抽出し、根拠外の具体手順や注意事項は追加しない。
- `不明点` では、根拠にない条件や例外を断定しないことを明示する。
- 残り: v2 scorecard で required_sections / completeness の改善幅を確認し、必要なら answer composer 本体側へ拡張する。

## 背景(なぜ今)

stg の 17問 smoke は PASS しているが、v2品質テストでは回答系24件が `answer_composition` で失敗した。
検索・引用は当たっている一方、回答が短く、製造現場で期待される「結論、手順、注意点、根拠」の構造がない。

## どんな課題か

- 期待挙動: 回答は用途に応じて `結論`, `手順/確認項目`, `判断基準`, `注意点`, `根拠`,
  `文書にない情報` を分けて提示する。
- 実際の挙動: 正しい文書から数文を抽出するだけで、根拠説明や作業者が使える粒度が不足する。
- `required_sections` がほぼ落ちており、商品としての見栄えが弱い。

## どこで起きたか

- 画面: `/chatbot`
- API: `POST /v1/chat/sessions`
- コード: `src/raku_rag/services/answer.py`, `src/raku_rag/chatbot/service.py`,
  `scripts/demo/chatbot_golden_scenarios.py`
- 環境: AWS stg
- run id / ingestion id / correlation id: 2026-06-30 stg v2 scorecard `/tmp/chatbot-v2-stg.json`
- 再現条件: v2 answer scenario 全般。例:
  - `モータ M8 の端子台ねじと基礎ボルト M16 の締付トルク、芯出し、絶縁抵抗を現場向けに整理して`
  - `受電盤 MCC-3 420V の点検前 LOTO について、誰が何を施錠し、検電・放電・接地をどう確認しますか`

## 影響

- 営業デモへの影響: 正しいが薄い回答に見え、価値が伝わりにくい。
- 本番クライアントへの影響: 作業者がそのまま行動できる粒度にならない。
- セキュリティ、監査、データ品質、UX への影響: 根拠の説明が弱いと、監査時に「なぜその結論か」を
  追いにくい。

## どう解決すべきか

1. ChatBot/RAG answer composer に製造業向けテンプレートを追加する。
2. 質問カテゴリごとに型を分ける:
   - lookup: `結論`, `確認項目`, `判断基準`, `根拠`
   - procedure: `結論`, `手順`, `注意`, `根拠`, `文書にない情報`
   - troubleshooting: `原因`, `暫定処置`, `恒久対策`, `効果`, `根拠`
3. 根拠セクションでは citation ID だけでなく、どの記述から結論になるかを短く説明する。
4. 文書にない情報は推測で埋めず、明示的に「文書内では確認できません」と出す。
5. v2 `required_sections` と `required_terms` の PASS 率を改善する。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- v2 answer scenario の `required_sections` が 80%以上 PASS する。
- 17問 smoke は 17/17 PASS を維持する。
- high-risk procedure は approved/effective citation なしに断定しない。
- 回答本文に根拠外推測が入らない。

## スコープ外

- safety/ACL/source policy の緩和。
- 有料LLM provider への無承認切替。
- UIだけで本文を整形すること。

## 参照

- `scripts/demo/chatbot_quality_v2_scenarios.json`
- `src/raku_rag/services/answer.py`
- `docs/production-readiness/chatbot-sellable-quality-plan.md`
- `issues/0051-chatbot-sellable-answer-quality-roadmap.md`
