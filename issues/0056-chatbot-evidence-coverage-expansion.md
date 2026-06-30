# 0056 — 正しい文書を引けても必要項目を抜き切れない(系統 = chatbot / retrieval-to-answer)

> Priority: **P1/High** / Status: Open / Labels: `chatbot`, `retrieval`, `answer-composition`, `rag-quality`

## 背景(なぜ今)

stg の v2品質テストでは expected citation hit rate が 100% だった一方、必要語句が抜ける失敗が多かった。
つまり検索は当たっているが、回答生成時にベスト文書の必要項目を使い切れていない。

## どんな課題か

- 期待挙動: 正しい文書が取れた場合、質問が要求する項目を文書内から網羅的に抽出する。
- 実際の挙動: 先頭/上位数文だけを抽出し、同じ文書内の重要項目を落とす。
- 例: `タグアウト`, `300℃未満`, `暫定処置`, `日常監視`, `湿度75%超`, `30μm` などが抜けた。

## どこで起きたか

- 画面: `/chatbot`
- API: `POST /v1/chat/sessions`, `/v1/search`
- コード: `src/raku_rag/services/answer.py`, `src/raku_rag/core/hybrid_retrieval.py`,
  `src/raku_rag/production.py`
- 環境: AWS stg
- run id / ingestion id / correlation id: 2026-06-30 stg v2 scorecard `/tmp/chatbot-v2-stg.json`
- 再現条件:
  - LOTO: citation は `safe-0331-loto` だが `タグアウト` や `活線作業は禁止` が抜ける。
  - PWHT: citation は `wi-0457-pwht` だが `300℃未満` が抜ける。
  - trouble case: citation は `tc-0258` だが `暫定`, `日常監視`, `18か月` が抜ける。

## 影響

- 営業デモへの影響: 「文書は見つけたが答えが浅い」印象になる。
- 本番クライアントへの影響: 作業判断に必要な条件が抜ける。
- セキュリティ、監査、データ品質、UX への影響: 根拠があるのに不足回答になるため、ユーザーが手動で
  文書を読み直す必要がある。

## どう解決すべきか

1. ベスト文書の周辺チャンクまたは同一 document_id の関連チャンクを answer composer に渡す。
2. 質問から要求項目を抽出し、各項目に対応する根拠文を探索する。
3. exact identifier がある場合は、候補を同一文書/同一設備に絞って coverage を上げる。
4. trouble case は構造化データから `原因`, `暫定処置`, `恒久対策`, `効果` を分けて使う。
5. raw context をログ出力しないまま、coverage diagnostics を scorecard に出す。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- expected citation hit rate を維持したまま required terms hit rate が大きく改善する。
- v2 answer scenario の completeness が 80%以上になる。
- 同一 tenant/ACL/source policy 範囲外の chunk を coverage 補完に使わない。
- raw retrieved context をログやAPIレスポンスに露出しない。

## スコープ外

- source/file/folder単位のチャット対象指定。
- 安全ゲートや承認状態の緩和。
- provider依存の有料reranker導入。

## 参照

- `scripts/demo/chatbot_quality_v2_scenarios.json`
- `src/raku_rag/services/answer.py`
- `src/raku_rag/production.py`
- `docs/production-readiness/chatbot-golden-scenarios.md`

