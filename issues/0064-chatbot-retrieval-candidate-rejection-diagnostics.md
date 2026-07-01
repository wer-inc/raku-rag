# 0064 — ChatBot検索候補の除外理由診断(系統 = chatbot / quality)

> Priority: **High** / Status: Open / Labels: `chatbot`, `quality`, `retrieval`, `observability`

## 背景(なぜ今)

ChatBotを販売品質へ近づける改善で、scorecardに任意のretrieval diagnosticsを追加した。
これにより `recall@k`、MRR、top document IDs、miss reasonは見えるようになったが、
検索内部の候補除外理由まではまだ追えない。

## どんな課題か

- 回答が薄い、または期待根拠を引用しない時に、候補がどの段階で落ちたかを十分に説明できない。
- 現状のscorecard診断は `/v1/search` の最終結果だけを見るため、vector候補、lexical候補、metadata exact候補、ACL/tombstone、rerank後の除外理由を分離できない。
- 生の検索本文を出さずに、運用者が「検索の問題か、回答合成の問題か」を特定できる形が必要。

## どこで起きたか

- 画面: `/chatbot` の回答品質確認、運用診断画面の将来拡張
- API: `POST /v1/search`, `POST /v1/chat/sessions`
- コード: `scripts/demo/chatbot_golden_scenarios.py`, `src/raku_rag/services/retrieval.py`, `apps/answer-service/server.py`
- 環境: local/stg scorecard
- run id / ingestion id / correlation id: なし
- 再現条件: expected document IDを持つChatBot golden scenarioで、期待文書がcitationまたはsearch top-kに出ない

## 影響

- 営業デモへの影響: 失敗時の原因説明が弱く、改善優先度を判断しにくい。
- 本番クライアントへの影響: ナレッジ追加後の「なぜ答えられないか」を運用者が自己解決しにくい。
- セキュリティ、監査、データ品質、UX への影響: 診断でraw contextを出すと漏洩リスクがあるため、参照IDと集計理由に限定する必要がある。

## どう解決すべきか

1. retrieval traceに、候補集合ごとの件数と除外理由をraw textなしで記録する。
2. `/internal/search` または管理者向け診断APIに、tenant/ACL済みの診断サマリだけを返すオプションを追加する。
3. scorecardの `--retrieval-diagnostics` が、候補段階別の `candidate_count`, `filtered_count`, `rerank_kept_count`, `rejection_reasons` を取り込めるようにする。
4. テストではraw chunk text、PII、権限外document IDが診断に入らないことを固定する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- scorecard JSONに候補段階別の診断サマリが出る。
- raw retrieved text、PII、secret、権限外文書IDが診断に含まれない。
- retrieval missを `zero_candidates`、`acl_or_tombstone_filtered`、`expected_doc_not_retrieved`、`rerank_dropped_expected_doc` などに分類できる。
- 既存のACL、tenant isolation、approved/effective evidence gateを弱めていない。

## スコープ外

- 顧客向けUIに生の検索debug情報を表示すること。
- source policy、ACL、manufacturing safety gateの緩和。
- LLM judgeや有料reranker導入そのもの。

## 参照

- `docs/production-readiness/chatbot-sellable-quality-plan.md`
- `docs/production-readiness/chatbot-golden-scenarios.md`
- `scripts/demo/chatbot_golden_scenarios.py`
