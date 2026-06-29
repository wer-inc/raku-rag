# 0032 — ChatBot 外部/匿名 widget 用の署名付きセッション入口が未実装(系統 = product / security / chatbot)

> Priority: **Medium** / Status: Addressed in Implementation / Labels: `product`, `security`, `chatbot`, `external`

## 対応メモ(2026-06-29)

- `POST /v1/chat/public-widget/sessions` を追加し、通常の authenticated `/v1/chat/sessions` と route を分離。
- public widget は `RAKU_CHAT_WIDGET_SECRET` で署名された token から tenant / widget / allowed_domains / collection scope を確定し、body の tenant/source/channel/collection/filter override を信頼しない。
- Origin が signed allowlist 外の場合は 403、invalid token は 401、per-widget/IP rate limit 超過は 429 で upstream 前に拒否。
- answer-service には `chat_anonymous` principal と `public_widget` channel、token-derived `collection_id`、server-derived widget metadata のみを転送。
- ChatBot source exposure policy は public widget turn で allowed domain と public document tag 設定を runtime check し、該当 policy がなければ RAG 実行前に fail-closed。

## 背景(なぜ今)

ChatBot 実装レビューで、`public_widget` channel や `external_anonymous` source exposure mode は型・policy 判定に存在する一方、外部顧客/匿名 widget 用の署名付き public session/token 入口が実装されていないことを確認した。

## どんな課題か

- 現状の `/v1/chat/*` は `AuthMiddleware` 配下で、通常の signed user context が必須。
- `channel: "public_widget"` を body で指定することはできるが、tenant config / domain allowlist / widget token から channel を確定する境界がない。
- 仕様では external customer chat modes は署名付き public session/widget context を使い、request body の tenant/source/filter override を信頼しない必要がある。

## どこで起きたか

- 画面: 外部公開 ChatBot widget
- API: `POST /v1/chat/sessions`
- コード:
  - `apps/api/src/app.module.ts`
  - `apps/api/src/chat/chat.controller.ts`
  - `src/raku_rag/chatbot/service.py`
- 環境: local implementation review
- run id / ingestion id / correlation id: none
- 再現条件:
  - 認証なしで external/public widget session を開始する導線が存在しない。
  - body の `channel` だけでは domain/widget validation が行われない。

## 影響

- 外部公開 ChatBot としてはまだ利用できない。
- 将来 public route を単純追加すると、body channel や source policy を誤信する実装になりやすい。
- external anonymous の ACL/filter/rate limit 境界が未確定。

## どう解決すべきか

1. Public widget 用の signed widget/session token 発行・検証境界を設計する。
2. tenant, channel, allowed domain, anonymous ACL scope, rate limit を token/server config 由来にする。
3. ChatController は public route と authenticated route を分け、body の tenant/source/filter/channel override を拒否または無視する。
4. external anonymous source exposure policy の domain/tag/approval checks を contract test で固定する。

## QA checklist

- [ ] 認証済み external user と anonymous widget の session start が区別される。
- [ ] body の tenant/source/filter/channel override が効かない。
- [ ] allowed domain 外から anonymous session を開始できない。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] API smoke で確認できる。

## 受け入れ条件(DoD)

- 外部公開用の署名付き widget/public session context が実装されている。
- anonymous は明示設定された tenant/source/document tag/rate limit のみ使う。
- 403/401/429 の regression test が追加されている。
- 内部 authenticated ChatBot の既存動作を壊していない。

## スコープ外

- body に tenant_id を渡して anonymous tenant を決めること。
- domain allowlist なしの public widget。
- live operator takeover / WebSocket 実装。

## 参照

- `specs/023-rag-chatbot-agent/spec.md` FR-005 / FR-005a / FR-047
- `specs/023-rag-chatbot-agent/contracts/chat-openapi.md`
- `apps/api/src/app.module.ts`
- `apps/api/src/chat/chat.controller.ts`
- `src/raku_rag/chatbot/service.py`
