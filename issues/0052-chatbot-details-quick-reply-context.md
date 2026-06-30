# 0052 — ChatBot「もう少し詳しく」が文脈なし検索になる(系統 = chatbot / UX)

> Priority: **P1/High** / Status: Open / Labels: `chatbot`, `ux`, `rag-quality`

## 背景(なぜ今)

stg の `/chatbot` で回答後に表示される「もう少し詳しく」をクリックすると、毎回
「承認済みの根拠だけでは回答を確定できません。担当者が確認できるよう引き継ぎます。」
と返ることがユーザー確認で見つかった。

## どんな課題か

- 期待挙動: 直前の回答と同じ根拠・同じ参照範囲で、より詳しい説明を返す。
- 実際の挙動: UI 表示は「もう少し詳しく」だが、API に送る値が `details` だけになり、
  RAG 検索に必要な設備名・文書名・前回質問が欠落する。
- 結果として、根拠不足判定または無関係検索になり、ユーザーには会話が壊れたように見える。

## どこで起きたか

- 画面: `/chatbot`
- API: `POST /v1/chat/sessions/:sessionId/messages`
- コード: `src/raku_rag/chatbot/service.py`, `apps/web/app/components/FullSaasScreen.tsx`
- 環境: AWS stg
- run id / ingestion id / correlation id: なし(ユーザー手動確認)
- 再現条件: 回答後の quick reply「もう少し詳しく」をクリックする。

## 影響

- 営業デモへの影響: 会話継続の自然さが崩れ、回答品質が低く見える。
- 本番クライアントへの影響: 現場ユーザーが追加確認できず、毎回人間引き継ぎになる。
- セキュリティ、監査、データ品質、UX への影響: ACL や承認済み根拠ルールは維持されるが、
  UX と RAG 品質評価上は重大な失敗になる。

## どう解決すべきか

1. `details` quick reply を前回質問・前回引用文書ID・前回回答を含むフォローアップ検索文に変換する。
2. UI 上の表示は「もう少し詳しく」のまま保つ。
3. regression test で `details` がそのまま RAG に渡らないことを確認する。
4. stg 反映時は回答後に「もう少し詳しく」を押し、同じ citation で回答が続くことを確認する。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 「もう少し詳しく」が `details` 単体ではなく、前回回答の文脈つきで処理される。
- 同じ collection/source policy の範囲内でのみ追加回答する。
- 既存の source exposure policy、ACL、approved/effective evidence gate を弱めない。
- regression test が追加されている。

## スコープ外

- 回答 composer 全体の売れる品質化。
- 曖昧質問全般の clarification policy 強化。
- policy bypass / chain-of-thought 拒否の包括対応。

## 参照

- `src/raku_rag/chatbot/service.py`
- `tests/unit/test_chatbot_service.py`
- `docs/production-readiness/chatbot-golden-scenarios.md`
