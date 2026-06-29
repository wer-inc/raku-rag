# 0025 — ChatBot設計のP0境界と既存RAG契約整合ギャップ(系統 = architecture / spec-quality)

> Priority: **High** / Status: Addressed in Spec / Labels: `architecture`, `spec-quality`, `chatbot`, `rag-contract`

## 背景(なぜ今)

`specs/023-rag-chatbot-agent/` の設計書を、`goal.md` の ChatBot 要件と既存 001 RAG 基盤へ載せる前提で網羅性・整合性チェックしたところ、実装タスク化前に解消すべき仕様ギャップが見つかった。

## 対応状況

2026-06-28 に 023 spec 一式へ反映済み。P0 は backend scenario lifecycle API を含み、管理 UI は P1 と整理した。`initial_message` は first turn として処理する。RAG connector は既存 `AnswerResponse.status` / citations / freshness を adapter で ChatBot metadata へ写像し、shared DTO を暗黙拡張しない方針に更新した。

## どんな課題か

- P0 では scenario を fixture seed するのか、管理 API で作成・レビュー・承認・公開するのかが設計書間で一致していない。
- `POST /v1/chat/sessions` の `initial_message` を処理するかどうかが契約と quickstart で揺れている。
- ChatBot 側が期待する RAG metadata (`answerable`, `no_answer_reason`, `risk_flags`, `identifier_hints`, `filters`) と、既存 001 の `AnswerResponse` / `SearchResponse` shape が一致していない。
- Chat API body に `api_version` / `tenant_id` を必須化する方針と、既存 facade の `api-version` response header 方針の関係が明示されていない。
- `ChatMessage.message_type` enum と API example の `"normal"` が不一致。
- Spec Kit の story priority 表記 `P1` と product slice の `P1 operations` が混ざり、tasks 生成時に優先度が誤解される可能性がある。

## どこで起きたか

- 仕様: `specs/023-rag-chatbot-agent/spec.md`
- 設計: `specs/023-rag-chatbot-agent/plan.md`
- データモデル: `specs/023-rag-chatbot-agent/data-model.md`
- API契約: `specs/023-rag-chatbot-agent/contracts/chat-openapi.md`
- quickstart: `specs/023-rag-chatbot-agent/quickstart.md`
- 既存DTO: `packages/shared/src/dto/answer.ts`, `packages/shared/src/dto/search.ts`
- 環境: local repository review
- run id / ingestion id / correlation id: none
- 再現条件: 023 design docs を横断し、既存 answer/search DTO と比較する。

## 影響

- 実装タスクが「fixture seed」と「管理 API 実装」の両方を P0 と解釈し、スコープが膨らむ。
- ChatBot RAG connector が既存 RAG DTO を薄く使えず、暗黙の DTO 拡張や二重契約が発生する。
- OpenAPI / shared DTO / frontend 実装で response shape が分岐し、契約テストが壊れやすい。
- 初回 message 処理の挙動が揺れると、Web Chat UI の最初の体験と quickstart が一致しない。
- 優先度表記が混乱すると Spec Kit tasks の順序が誤る。

## どう解決すべきか

1. P0 境界を明文化する。推奨は「P0 は backend scenario lifecycle API あり、UI は fixture/minimal、管理 UI は P1」または「P0 は seed script のみ、scenario API は P1」のどちらかに統一する。
2. `initial_message` の挙動を統一する。推奨は `create session` を `create+first turn` として、response に `assistant_message` / `state` を返す、または quickstart を `POST /messages` へ分ける。
3. RAG connector は既存 `AnswerResponse.status` から answerable を導出するか、既存 shared DTO/OpenAPI を正式拡張するかを決める。Chat-specific metadata は原則 ChatBot 側の `RagInteraction` に保存する。
4. API versioning は既存 `api-version` header を継承し、body fields は Chat API 固有 envelope として採用するかどうかを contracts に明記する。
5. `message_type` enum と examples を統一する。
6. Story priority は Spec Kit の優先度(`P1/P2`)と product phase(`P0/P1/P2`)が混ざらない表記へ直す。

## QA checklist

- [ ] 023 docs の P0/P1/P2 境界が全ファイルで一致している。
- [ ] Chat API examples と data-model enum が一致している。
- [ ] Existing RAG connector contract が `packages/shared/src/dto/answer.ts` / `search.ts` と矛盾しない。
- [ ] `initial_message` の smoke と API response が一致している。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] API smoke で確認できる。

## 受け入れ条件(DoD)

- 023 の `spec.md`, `data-model.md`, `contracts/chat-openapi.md`, `quickstart.md`, `checklists/requirements.md` が同じ P0 境界を説明している。
- RAG connector が既存 RAG DTO をどう使うか、またはどの DTO を正式拡張するかが明文化されている。
- 初回メッセージ、scenario publication、handoff、ticket stub、feedback、metrics の acceptance smoke が矛盾なく成立する。
- 後続の `/speckit-tasks` が曖昧な判断なしにタスクを生成できる。

## スコープ外

- ChatBot 実装そのもの。
- live CRM / Slack / email / phone / CCaaS adapter の実装。
- 既存 RAG の安全ルール、ACL、監査、approval flow の緩和。

## 参照

- `specs/023-rag-chatbot-agent/spec.md`
- `specs/023-rag-chatbot-agent/data-model.md`
- `specs/023-rag-chatbot-agent/contracts/chat-openapi.md`
- `specs/023-rag-chatbot-agent/quickstart.md`
- `packages/shared/src/dto/answer.ts`
- `packages/shared/src/dto/search.ts`
