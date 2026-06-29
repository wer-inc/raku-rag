# 0029 — ChatBot source exposure policy が RAG 実行前に効いていない(系統 = security / rag / chatbot)

> Priority: **P0** / Status: Addressed in Implementation / Labels: `security`, `rag`, `chatbot`, `source-exposure`

## 背景(なぜ今)

ChatBot 実装レビューで、data source ChatBot exposure policy が citation の後処理として適用されていることを確認した。仕様では ChatBot が search/answer results を使う前に、`principal ACL ∩ datasource exposure ∩ scenario rag_policy ∩ lifecycle/approval state` の交差で絞る必要がある。

## どんな課題か

- 現状は既存 RAG answer を先に実行し、その後に citations を ChatBot policy でフィルタしている。
- RAG answer が許可 source と禁止 source の混在根拠から本文を生成した場合、許可 citation が1件でも残ると、禁止 source 由来の情報が本文に混ざる可能性がある。
- 現行 `Citation` DTO には `collection_id` がないため、citation 後処理だけでは collection-scoped policy を完全に検証できない。
- 仕様上は、ChatBot exposure policy を RAG 検索・回答の前段で effective scope として適用すべき。

## どこで起きたか

- 画面: `/chatbot`
- API: `POST /v1/chat/sessions/{session_id}/messages`
- コード:
  - `src/raku_rag/chatbot/service.py` `_run_rag_turn`
  - `apps/answer-service/server.py` ChatBot RAG callback
- 環境: local implementation review
- run id / ingestion id / correlation id: none
- 再現条件:
  - 同一 collection に ChatBot 許可 source と ChatBot 禁止 source を置く。
  - RAG が両方を citation に含める質問を投げる。
  - 許可 citation が1件以上残ると、禁止 source 由来の本文が返らないことを確認する。

## 影響

- 外部 ChatBot / public widget 公開時の情報漏洩リスク。
- disabled source の存在や内容を ChatBot 回答本文で漏らすリスク。
- 仕様 `FR-028a` / `FR-028c` と実装の不整合。

## どう解決すべきか

1. ChatBot turn の RAG 呼び出し前に、source exposure policy と scenario rag_policy から許可 source/collection/document tag filter を計算する。
2. 既存 RAG answer/search adapter に server-side filter metadata を渡し、検索候補そのものを許可範囲に絞る。
3. RAG DTO 拡張が必要なら `packages/shared` と OpenAPI を先に更新する。
4. collection-scoped policy を検証できるよう、pre-RAG filter または citation metadata に collection scope を持たせる。
5. 後処理 citation filter は防御層として残すが、本文生成後の唯一の制御にしない。

## QA checklist

- [ ] 許可 source と禁止 source が混在しても禁止 source 由来の本文が返らない。
- [ ] ChatBot 許可 source が0件の場合は insufficient evidence / handoff になる。
- [ ] external anonymous は public tag / allowed domain / approved effective のみ使う。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] API smoke で確認できる。

## 受け入れ条件(DoD)

- RAG 呼び出し前に ChatBot effective source scope が適用されている。
- 混在 citation の regression test が追加されている。
- ChatBot response body に禁止 source 由来の情報が出ないことをテストで確認している。
- 既存 RAG の ACL、tombstone、approval/effective-state を弱めていない。

## スコープ外

- ChatBot 専用 vector store の作成。
- demo-only bypass や source policy の無効化。
- 既存 RAG ACL の緩和。

## 参照

- `specs/023-rag-chatbot-agent/spec.md` FR-028a / FR-028c
- `specs/023-rag-chatbot-agent/contracts/chat-openapi.md` Effective ChatBot source scope
- `src/raku_rag/chatbot/service.py`
- `apps/answer-service/server.py`
- Implementation note: P0 now fails closed before RAG unless a collection-wide ChatBot source policy can be enforced through the existing answer contract. Source-specific policy is kept as draft/invalid until the RAG adapter accepts source-level filters.
