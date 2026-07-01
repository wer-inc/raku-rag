# 0065 — ChatBot Markdown table rendering (系統 = chatbot / ux)

> Priority: **P2/Medium** / Status: Resolved / Labels: `chatbot`, `ux`, `markdown`

## 背景(なぜ今)

`/chatbot` の quick reply「判断基準を表にする」は、回答本文として Markdown table を返す想定だが、
frontend の chat bubble は本文を plain text として表示していた。

## どんな課題か

- Markdown table、箇条書き、番号リスト、太字が UI 上で構造化表示されない。
- 「判断基準を表にする」を押しても、表ではなく `|---|` を含む文字列として見える。
- backend の回答改善が frontend 表示で伝わらず、商品品質が低く見える。

## どこで起きたか

- 画面: `/chatbot`
- API: `/v1/chat/sessions/:sessionId/messages`
- コード: `apps/web/app/components/FullSaasScreen.tsx`
- 環境: local / stg
- run id / ingestion id / correlation id: N/A
- 再現条件: assistant message が GitHub Flavored Markdown の table を含む。

## 影響

- 営業デモで「表にする」系の回答がただのテキストに見え、期待価値が伝わりにくい。
- 本番クライアントでも判断基準、手順、注意点の可読性が落ちる。
- セキュリティ境界そのものへの影響はないが、Markdown renderer 導入時に raw HTML を許可すると
  XSS 面の論点が増える。

## どう解決すべきか

1. assistant message だけ Markdown/GFM renderer で表示する。
2. raw HTML は許可せず、表示要素を paragraph/list/table/code/blockquote などに限定する。
3. table は chat bubble 内で横スクロールできるようにし、mobile で幅崩れしないようにする。
4. user message は plain text のまま維持する。

## QA checklist

- [ ] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- ChatBot assistant response の Markdown table が表として表示される。
- 箇条書き、番号リスト、太字、inline code が破綻しない。
- raw HTML はレンダリングしない。
- chat bubble の横幅を壊さず、table は横スクロールできる。

## スコープ外

- backend の structured response schema 化。
- citation UI の仕様変更。
- user message の Markdown 化。
- raw HTML、画像、任意リンクの許可。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx`
- `apps/web/app/globals.css`
- `apps/web/package.json`
