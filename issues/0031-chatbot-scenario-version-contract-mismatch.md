# 0031 — ChatBot scenario version API が contract と一致していない(系統 = api / qa / chatbot)

> Priority: **Medium** / Status: Addressed in Implementation / Labels: `api`, `qa`, `chatbot`, `contract`

## 対応メモ(2026-06-29)

- `PUT /v1/chat/scenarios/{scenario_id}/versions/{version_id}` を NestJS facade と answer-service internal route に追加。
- `ChatScenario` が複数 `ScenarioVersion` を保持し、steps / slots / validation / rag_policy / actions / templates / handoff_conditions を version body として保持するように変更。
- `submit-review -> approve -> publish` の lifecycle を version 単位にし、未承認 publish は `scenario_version_not_approved`、published/archived version の PUT は `scenario_version_immutable` で拒否。
- session/turn の `scenario_version_id` は active published version から記録される。
- OpenAPI / shared DTO / route-level e2e / Python unit を更新。

## 背景(なぜ今)

ChatBot 実装レビューで、spec/contract/quickstart が scenario version の作成・更新 API を定義している一方、実装には該当する `PUT /v1/chat/scenarios/{scenario_id}/versions/{version_id}` が存在しないことを確認した。

## どんな課題か

- contract では deterministic scenario を seed/update して submit-review / approve / publish する流れになっている。
- 実装では `POST /v1/chat/scenarios` と action 系 `POST` はあるが、version body の update endpoint がない。
- quickstart 通りに scenario definition を投入できず、P0 の backend scenario lifecycle API が部分的になる。

## どこで起きたか

- 画面: 将来の ChatBot scenario admin UI
- API: `PUT /v1/chat/scenarios/{scenario_id}/versions/{version_id}`
- コード:
  - `apps/api/src/chat/chat.controller.ts`
  - `apps/answer-service/server.py`
  - `src/raku_rag/chatbot/service.py`
- 環境: local implementation review
- run id / ingestion id / correlation id: none
- 再現条件:
  - quickstart の scenario version PUT を実行する。
  - 404 または route missing になる。

## 影響

- spec kit の quickstart がそのまま実行できない。
- scenario の steps / slot validation / rag_policy / response template を version として更新できない。
- P1 scenario UI 実装時に API 契約が再調整になる。

## どう解決すべきか

1. `PUT /v1/chat/scenarios/{scenario_id}/versions/{version_id}` を NestJS facade と answer-service に追加する。
2. ScenarioVersion body に steps, required/optional slots, validation rules, rag_policy, actions, templates, handoff conditions を保持する。
3. approve/publish は immutable version に対して行い、published version を session/message に記録する。
4. OpenAPI と shared DTO と quickstart を実装に合わせて contract test で固定する。

## QA checklist

- [ ] quickstart の scenario seed/update が通る。
- [ ] draft -> in_review -> approved -> published が通る。
- [ ] 未承認 version は publish できない。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] API smoke で確認できる。

## 受け入れ条件(DoD)

- scenario version PUT が実装され、contract と OpenAPI に載っている。
- route-level e2e test が追加されている。
- scenario version が session/message に記録される。
- quickstart が手順通り通る。

## スコープ外

- polished scenario editor UI。
- live CRM/business action adapter。
- scenario approval の bypass。

## 参照

- `specs/023-rag-chatbot-agent/contracts/chat-openapi.md`
- `specs/023-rag-chatbot-agent/quickstart.md`
- `apps/api/src/chat/chat.controller.ts`
- `apps/answer-service/server.py`
- `src/raku_rag/chatbot/service.py`
