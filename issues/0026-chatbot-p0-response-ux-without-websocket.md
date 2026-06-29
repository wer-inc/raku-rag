# 0026 — ChatBot P0のHTTP応答待ちUXを明文化する(系統 = ux / spec-quality)

> Priority: **Medium** / Status: Addressed in Spec / Labels: `ux`, `spec-quality`, `chatbot`

## 背景(なぜ今)

ChatBot P0 は WebSocket/SSE を使わず HTTP request/response で始める方針だが、UI が無反応に見えないための typing/progress/timeout/retry/handoff UX が設計書上で十分に明文化されていなかった。

## どんな課題か

- WebSocket を使わないこと自体は問題ない。
- ただし送信後に画面が無反応だと、ユーザーには「止まった」「返ってこない」と見える。
- P0 では通信方式ではなく、即時表示・進行状態・timeout時の導線で realtime 感を作る必要がある。

## どこで起きたか

- 仕様: `specs/023-rag-chatbot-agent/spec.md`
- API契約: `specs/023-rag-chatbot-agent/contracts/chat-openapi.md`
- quickstart: `specs/023-rag-chatbot-agent/quickstart.md`
- 環境: design review
- run id / ingestion id / correlation id: none
- 再現条件: P0 HTTP blocking 方針の UX を確認する。

## 影響

- UI/UX 上、回答待ちでユーザーが不安になる。
- RAG/LLM 応答が遅いケースで離脱や重複送信が起きやすい。
- WebSocket が必要だと誤解され、P0 スコープが膨らむ。

## どう解決すべきか

1. P0 は HTTP request/response のままにする。
2. UI は送信直後に user message を optimistic display する。
3. HTTP pending 中は bot typing/progress states を表示する。
4. delay/timeout threshold 後は retry と human handoff を表示する。
5. SSE は P1、WebSocket は live operator takeover が必要になった時まで保留する。

## QA checklist

- [ ] 送信直後に user message が表示される。
- [ ] HTTP pending 中に bot typing/progress が表示される。
- [ ] timeout 時に retry と handoff が表示される。
- [ ] WebSocket/SSE なしで P0 smoke が成立する。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。

## 受け入れ条件(DoD)

- 023 spec/contract/quickstart/checklist に P0 response UX が明記されている。
- WebSocket 不要の判断と、将来 SSE/WebSocket を入れる条件が説明可能である。
- ユーザーが回答待ちで無反応に見えない UX smoke を定義できている。

## スコープ外

- WebSocket 実装。
- SSE streaming 実装。
- live operator takeover 実装。

## 参照

- `specs/023-rag-chatbot-agent/spec.md`
- `specs/023-rag-chatbot-agent/contracts/chat-openapi.md`
- `specs/023-rag-chatbot-agent/quickstart.md`
