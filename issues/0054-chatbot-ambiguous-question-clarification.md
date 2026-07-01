# 0054 — ChatBotが曖昧質問に確認質問せず断定回答する(系統 = chatbot / safety-ux)

> Priority: **P1/High** / Status: Open / Labels: `chatbot`, `clarification`, `safety`, `rag-quality`

## 実装メモ(2026-07-01)

- ChatBot service に retrieval 前の `needs_clarification` 判定を追加した。
- 対象不明のボルト締付トルク、対象槽/濃度/液量がない薬液投入量、点検/アラームが曖昧な E-152 質問、
  SCC と塗装ピンホールをまとめた作業指示化を確認質問に落とす。
- clarification response は `ai_action=ask_clarification` とし、`answerable=false`,
  `no_answer_reason=clarification_required` を返す。
- 確認質問では数値・作業手順を断定せず、不足スロットを具体的に聞く。

## 背景(なぜ今)

stg の v2品質テストで、`ボルトの締付トルクだけ教えて` のような曖昧質問に対し、ChatBot が対象設備や
ボルト種別を確認せず、M8/M16 の数値をそのまま回答した。製造現場では、対象が違えば危険な誤案内に
なる。

## どんな課題か

- 期待挙動: 設備、工程、文書ID、エラーコード、対象部品などが不足している場合は確認質問を返す。
- 実際の挙動: 近い文書を検索できると、そのまま数値や手順を断定してしまう。
- `answerable=True` の前に「質問が十分に特定されているか」を判定する層が不足している。

## どこで起きたか

- 画面: `/chatbot`
- API: `POST /v1/chat/sessions`, `POST /v1/chat/sessions/:sessionId/messages`
- コード: `src/raku_rag/chatbot/service.py`, `src/raku_rag/services/answer.py`
- 環境: AWS stg
- run id / ingestion id / correlation id: 2026-06-30 stg v2 scorecard `/tmp/chatbot-v2-stg.json`
- 再現条件:
  - `ボルトの締付トルクだけ教えて`
  - `E-152 の対応を教えて。点検とアラームのどちらかは分かりません`
  - `薬液濃度が低いです。どれくらい足せばいいですか`

## 影響

- 営業デモへの影響: 「賢く確認してくれる」印象ではなく、危なっかしい Bot に見える。
- 本番クライアントへの影響: 誤った作業条件や数値を現場に出すリスクがある。
- セキュリティ、監査、データ品質、UX への影響: 製造安全上の high-risk gate 以前に、
  ambiguity gate が必要。

## どう解決すべきか

1. ChatBot service に ambiguity classifier を追加する。
2. 対象が複数あり得る語彙を検出する: `ボルト`, `トルク`, `対応`, `エラー`, `薬液濃度`,
   `手順`, `基準`, `この作業` など。
3. 検索候補が複数文書/複数設備に分かれる場合も clarification に落とす。
4. 返答は `ai_action=ask_clarification` とし、選択肢例を提示する。
5. v2 ambiguity_clarification 4件を 100% PASS にする。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 曖昧質問では数値・作業手順を断定しない。
- clarification response に不足スロットと具体例が含まれる。
- 明確な質問は既存通り answer_with_citations になる。
- v2 ambiguity_clarification scenario が全件 PASS する。

## スコープ外

- 安全ルールや承認済み根拠ルールの緩和。
- 全業界向けの一般 NLU 構築。
- UIだけでの確認質問制御。

## 参照

- `scripts/demo/chatbot_quality_v2_scenarios.json`
- `src/raku_rag/chatbot/service.py`
- `docs/production-readiness/chatbot-sellable-quality-plan.md`
