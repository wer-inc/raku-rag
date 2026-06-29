# 0030 — ChatBot 管理系 API に role gate がない(系統 = security / authz / chatbot)

> Priority: **High** / Status: Addressed in Implementation / Labels: `security`, `authz`, `chatbot`, `api`

## 背景(なぜ今)

ChatBot 実装レビューで、source exposure policy、scenario lifecycle、metrics、export/deletion などの管理系 API が `AuthMiddleware` で認証される一方、エンドポイントごとの role gate が未実装であることを確認した。

## どんな課題か

- 任意の authenticated user が source exposure policy を upsert できる可能性がある。
- 任意の authenticated user が scenario を作成・承認・公開・rollback できる可能性がある。
- metrics、export、deletion request も仕様上は管理者/監査権限が必要だが、現状は ChatController 全体が同じ認証境界に載っている。
- 仕様では role 別に許可範囲が定義されている。

## どこで起きたか

- 画面: `/chatbot` および将来の ChatBot admin UI
- API:
  - `PUT /v1/chat/source-exposure-policies/{policy_id}`
  - `POST /v1/chat/scenarios/*`
  - `GET /v1/chat/metrics`
  - `POST /v1/chat/sessions/export`
  - `POST /v1/chat/sessions/{session_id}/delete-request`
- コード:
  - `apps/api/src/chat/chat.controller.ts`
  - `src/raku_rag/chatbot/service.py`
- 環境: local implementation review
- run id / ingestion id / correlation id: none
- 再現条件:
  - `field_user` または通常 user token で source exposure policy upsert / scenario publish を呼ぶ。
  - 403 ではなく成功する場合、再現。

## 影響

- 低権限ユーザーが内部 source を ChatBot に露出させるセキュリティリスク。
- scenario の承認/公開フローが形だけになり、運用責任者の承認を bypass できる。
- metrics/export/deletion の監査境界が曖昧になる。

## どう解決すべきか

1. NestJS ChatController か service 層に ChatBot role guard を追加する。
2. `source exposure policy manage`: `tenant_admin`, `scenario_admin`, privileged data admin のみに制限する。
3. `scenario approve/publish/archive/rollback`: `tenant_admin`, `scenario_approver` のみに制限する。
4. `metrics/export/deletion`: spec の role matrix に合わせて制限し、403 contract test を追加する。

## QA checklist

- [ ] 通常 user / field_user は source exposure policy を変更できない。
- [ ] 通常 user / field_user は scenario approve/publish/rollback できない。
- [ ] session owner は自分の session 操作だけできる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] API smoke で確認できる。

## 受け入れ条件(DoD)

- ChatBot 管理 API に role gate が実装されている。
- 403 regression test が NestJS e2e と Python service unit のどちらか、または両方に追加されている。
- OpenAPI / shared DTO / spec の role matrix と実装が一致している。
- 既存 user-facing chat send/handoff は必要以上に塞がれていない。

## スコープ外

- RBAC を frontend 表示制御だけで済ませること。
- demo-only 管理者 bypass。
- ChatBot 以外の既存 admin API 全面見直し。

## 参照

- `specs/023-rag-chatbot-agent/contracts/chat-openapi.md` Role / policy matrix
- `apps/api/src/chat/chat.controller.ts`
- `apps/api/src/app.module.ts`
- `src/raku_rag/chatbot/service.py`
- Implementation note: NestJS facade and Python service both enforce role gates for source policies, scenarios, metrics, handoff package read, export, deletion, and retention routes.
