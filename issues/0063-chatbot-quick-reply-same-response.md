# 0063 — ChatBot quick reply が同じ返答になる(系統 = chatbot / conversational-ux)

> Priority: **P1/High** / Status: In progress / Labels: `chatbot`, `ux`, `rag-quality`

## 背景(なぜ今)

`/chatbot` の回答後に表示される quick reply を押しても、`この根拠でもう少し詳しく`,
`手順だけ見る`, `判断基準を表にする`, `注意点を確認` が同じような返答になることをユーザー確認で再検出した。

## どんな課題か

- 期待挙動: ボタンごとに、直前の承認済み根拠を `手順`, `判断基準`, `注意点`, `根拠` の用途別に再整形する。
- 実際の挙動: 追加依頼をRAGに投げ直し、最終的な回答フォーマットも共通なため、ユーザーには同じ返答に見える。
- 追加課題: `この根拠でもう少し詳しく` は意味が曖昧で、他のボタンと役割が重複する。

## どこで起きたか

- 画面: `/chatbot`
- API: `POST /v1/chat/sessions/:sessionId/messages`
- コード: `src/raku_rag/chatbot/service.py`, `apps/web/app/components/FullSaasScreen.tsx`
- 環境: AWS stg / local
- run id / ingestion id / correlation id: なし
- 再現条件: 根拠付き回答後に quick reply を複数クリックする。

## 影響

- 営業デモへの影響: 会話継続が機械的に見え、商品価値が下がる。
- 本番クライアントへの影響: 現場ユーザーが「どの操作を押せば何が得られるか」を学習できない。
- セキュリティ、監査、データ品質、UX への影響: 安全ルール自体は維持されるが、不要な再検索と同型返答により品質評価と信頼が落ちる。

## どう解決すべきか

1. `この根拠でもう少し詳しく` を表示候補から外す。
2. `手順だけ見る`, `判断基準を表にする`, `注意点を確認`, `根拠を確認する` を回答内容に応じて条件付き表示する。
3. follow-up は追加RAG検索ではなく、直前回答の承認済み citation と保存済み回答本文から再整形する。
4. 各ボタンのレスポンス形式を固定し、同一レスポンスにならないことを回帰テストで固定する。

## 実装メモ(2026-07-01 追記)

- stg deploy run `28511580979` 後の smoke で、水圧試験 quick reply の `steps` が `1.5` / `30` を落とし、
  `cautions` が初回候補に出ない回帰を確認した。
- 水圧・保持時間・校正済み圧力計などの基準語と、立入禁止・バリケード・急減圧などの注意語を
  quick reply 抽出語に追加した。
- `steps` follow-up は質問が数値条件を求める場合、直前の承認済み回答から基準値も併せて残す。
- 複雑な回答では `手順`, `判断基準`, `注意点`, `根拠` を最大4個まで表示できるように戻した。
- `test_hydrotest_quick_replies_keep_numeric_steps_and_cautions` で、追加RAG検索なしに
  `1.5MPa`, `30分`, `0.3MPa`, `バリケード`, `急減圧` が残ることを固定した。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- `details` ボタンが回答下に表示されない。
- `steps`, `criteria_table`, `cautions` がそれぞれ別フォーマットを返す。
- follow-up で追加RAG検索を呼ばず、直前の承認済み引用範囲だけを使う。
- regression test が追加または更新されている。
- 既存の source exposure policy、ACL、承認済み根拠ルールを弱めていない。

## スコープ外

- raw retrieved context の表示。
- CRM/Slack/チケット連携の本実装。
- safety/security refusal の緩和。

## 参照

- `issues/0052-chatbot-details-quick-reply-context.md`
- `issues/0057-chatbot-contextual-quick-replies.md`
- `src/raku_rag/chatbot/service.py`
- `tests/unit/test_chatbot_service.py`
