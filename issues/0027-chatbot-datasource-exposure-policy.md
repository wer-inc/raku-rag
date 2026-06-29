# 0027 — ChatBotが使えるデータソース範囲を明文化する(系統 = security / architecture / ux)

> Priority: **High** / Status: Addressed in Spec / Labels: `security`, `architecture`, `chatbot`, `datasource`

## 背景(なぜ今)

ChatBot は社内だけでなく外部顧客や匿名公開ウィジェットからも使う想定がある。その場合、既存 RAG の ACL だけでなく、データソースごとに ChatBot で使ってよいかを設定できる必要がある。

## どんな課題か

- 既存 RAG に登録済みのデータソースでも、ChatBot へ出したくないものがある。
- 社内 authenticated ChatBot では使えるが、外部 authenticated / anonymous ChatBot では使わせたくない source がある。
- 公開 ChatBot では、明示的に public chat 許可された approved/effective 文書だけを使うべき。
- 設定が曖昧だと、外部ユーザーに内部文書や存在情報が漏れる可能性がある。

## どこで起きたか

- 仕様: `specs/023-rag-chatbot-agent/spec.md`
- データモデル: `specs/023-rag-chatbot-agent/data-model.md`
- API契約: `specs/023-rag-chatbot-agent/contracts/chat-openapi.md`
- quickstart: `specs/023-rag-chatbot-agent/quickstart.md`
- 環境: design review
- run id / ingestion id / correlation id: none
- 再現条件: 外部公開 ChatBot がどの source を使えるかを確認する。

## 影響

- 外部公開時の情報漏洩リスク。
- データソース所有者が ChatBot 露出可否を制御できない。
- シナリオ filter と ACL の責務が混ざり、運用説明が難しくなる。
- disabled source の存在を Bot 応答で漏らすリスク。

## どう解決すべきか

1. ChatBot access は deny-by-default にする。
2. Effective scope を `principal ACL ∩ datasource exposure ∩ scenario rag_policy ∩ lifecycle/approval state` と定義する。
3. データソース/collection ごとに `disabled`, `internal_authenticated`, `external_authenticated`, `external_anonymous` を設定できるようにする。
4. 外部匿名では public widget/domain allowlist、anonymous ACL scope、public document tag、approved/effective を必須にする。
5. disabled/non-public source は insufficient evidence として扱い、存在を露出しない。

## QA checklist

- [ ] disabled source は ChatBot 回答に使われない。
- [ ] internal authenticated のみ許可された source は external chat で使われない。
- [ ] external anonymous は explicitly public な source/tag/document だけを使う。
- [ ] source visibility を body override できない。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] API smoke で確認できる。

## 受け入れ条件(DoD)

- 023 spec/data-model/contracts/quickstart/checklist に data source ChatBot exposure policy が明記されている。
- 後続 tasks で datasource policy API、contract test、security test、UI setting が迷わず生成できる。
- 既存 RAG の ingestion/vector/ACL/deletion/approval flow は複製されない。

## スコープ外

- 別 ChatBot 専用 vector store の作成。
- 既存 RAG ACL の緩和。
- public chat に内部専用データを出す demo-only bypass。

## 参照

- `specs/023-rag-chatbot-agent/spec.md`
- `specs/023-rag-chatbot-agent/data-model.md`
- `specs/023-rag-chatbot-agent/contracts/chat-openapi.md`
- `specs/023-rag-chatbot-agent/quickstart.md`
