# 0057 — ChatBotのquick replyを回答内容に応じて文脈付きにする(系統 = chatbot / conversational-ux)

> Priority: **P2/Medium** / Status: In progress / Labels: `chatbot`, `ux`, `conversation`, `rag-quality`

## 実装メモ(2026-06-30)

- 通常の根拠付き回答では `人間に相談する` quick reply を出さず、`この根拠でもう少し詳しく` のみにした。
- `details` は引き続きサーバー側で前回質問・引用 document_id に展開し、文脈なし検索を避ける。
- 人間対応の文言は `担当者に確認依頼` に統一し、通常回答時は常時表示しない。
- 回答内容に応じて `手順だけ見る`, `注意点を確認`, `判断基準を表にする`, `根拠を確認する` を最大4個で出し分けるようにした。
- quick reply value は短い action のまま、サーバー側で前回質問・引用 document_id を含む follow-up 検索文へ展開する。
- stg 再確認で follow-up 検索文に UI 用の整形済み回答本文が混ざると、全 quick reply が根拠不足に倒れることを確認した。
  検索文は元質問・追加依頼・引用 document_id に絞り、`根拠を確認する` は直前のフィルタ済み citation summary を返す。

## 背景(なぜ今)

現在の ChatBot quick reply は主に「もう少し詳しく」「人間に相談する」だけで、内部値も抽象的だった。
`details` が文脈なし検索になった不具合は 0052 で扱うが、商品品質としては回答内容に合わせた
具体的な追加操作が必要。

## どんな課題か

- 期待挙動: 回答後に `手順だけ表示`, `注意点を詳しく`, `判断基準を表にする`, `根拠を確認する`
  など、前回回答に紐づいた quick reply が出る。
- 実際の挙動: 汎用の quick reply だけで、次の質問が自然につながらない。
- quick reply の value は検索可能な文脈またはサーバー側 action として扱う必要がある。

## どこで起きたか

- 画面: `/chatbot`
- API: `POST /v1/chat/sessions/:sessionId/messages`
- コード: `src/raku_rag/chatbot/service.py`, `apps/web/app/components/FullSaasScreen.tsx`,
  `packages/shared/src/dto/chat.ts`
- 環境: local, AWS stg
- run id / ingestion id / correlation id: なし
- 再現条件: 任意の回答後に quick reply を確認する。

## 影響

- 営業デモへの影響: 会話が一問一答に見え、業務支援感が弱い。
- 本番クライアントへの影響: ユーザーが次に何を聞けばよいか分からない。
- セキュリティ、監査、データ品質、UX への影響: 文脈なし quick reply は誤検索や不要な handoff を誘発する。

## どう解決すべきか

1. answer category に応じて quick reply を生成する。
2. quick reply value は `action` + `context_ref` 形式にするか、サーバー側で前回文脈から展開する。
3. `根拠を確認する` は citation summary を返し、raw context は出さない。
4. `判断基準を表にする` は既存 citation 範囲内の再構成に限定する。
5. UI では過剰なボタン数を避け、2-4個に制限する。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- quick reply が文脈なしの自由文検索にならない。
- 回答カテゴリに応じた追加アクションが出る。
- 追加アクションでも citation/source policy/ACL が維持される。
- Playwright または API smoke で quick reply follow-up が確認できる。

## スコープ外

- 会話型エージェントの長期メモリ。
- raw retrieved context の表示。
- safety/security refusal の緩和。

## 参照

- `issues/0052-chatbot-details-quick-reply-context.md`
- `src/raku_rag/chatbot/service.py`
- `apps/web/app/components/FullSaasScreen.tsx`
- `packages/shared/src/dto/chat.ts`
