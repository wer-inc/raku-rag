# 0069 — public ingest の approval metadata で根拠文書レビューを迂回できる可能性(系統 = security / approval)

> Priority: **P1 / High** / Status: Open / Labels: `security`, `manufacturing`, `approval`, `ingest`, `review-gate`

## 背景(なぜ今)

file upload / 外部 datasource 取込がまず根拠文書レビューに入るかを確認した際、UI の既定動作は
`pending_review` で安全側だが、公開 API 境界の `/v1/ingest` は `manufacturing.approval_status` を
リクエスト body からそのまま answer-service に転送していることが分かった。

外部 datasource sync は保存済み datasource の `approval_policy` から承認状態を導出し、sync body で
`approved` を自己付与できない設計になっている。一方、単体 ingest は同等の信頼/ロール判定が見えない。

## どんな課題か

- 期待挙動: product path の file/text ingest は既定で `pending_review` になり、`reviewer` または
  admin 系ロールの明示的な文書承認を経て初めて正式根拠(`approved` + effective)になる。
- 実際の懸念: `/v1/ingest` の request body に
  `manufacturing: { approval_status: "approved", effective_date: "YYYY-MM-DD", approval_source: "imported" }`
  を含めると、facade はその metadata を転送し、answer-service は `ManufacturingDocumentMetadata`
  として永続化する。
- UI の `APPROVAL_WORKFLOW_ENABLED` は既定 ON で `pending_review` を送るが、ブラウザ UI は
  security boundary ではない。API 直呼び・壊れた client・将来の別 uploader でレビューキューを
  迂回できる余地が残る。
- `issues/0016` は承認 transition / internal boundary のロール未検査を扱う。本件は「初回 ingest
  metadata で approved を作れてしまう」入口なので別課題として切る。

## どこで起きたか

- 画面: `/sources/new` の通常 UI は既定 `pending_review`。ただし UI 既定に依存している。
- API: `POST /v1/ingest`
- コード:
  - `apps/api/src/ingest/ingest.controller.ts` — `body.manufacturing` をそのまま internal ingest へ転送。
  - `apps/answer-service/server.py` — `_mfg_metadata_from_body(...)` が body の approval block から
    metadata を構築。
  - `src/raku_rag/production.py` — `ingest_document(..., manufacturing_metadata=...)` が成功時に
    `attach_manufacturing_metadata(...)` で Document/Chunk metadata に永続化。
  - `apps/web/app/components/FullSaasScreen.tsx` — UI 既定は `APPROVAL_WORKFLOW_ENABLED` により
    `pending_review` だが、これは server-side 強制ではない。
- 環境: local code review。live/stg reproduction は未実施。
- run id / ingestion id / correlation id: なし。
- 再現条件:
  1. reviewer/admin ではない通常 principal で `/v1/ingest` を呼ぶ。
  2. body に `manufacturing.approval_status="approved"` と有効な `effective_date` を含める。
  3. 取込後、該当文書が `approved` として search/answer の正式根拠候補になるか確認する。

## 影響

- 営業デモへの影響: デモ UI では発火しにくいが、API smoke や補助 uploader が `approved` を送ると
  レビュー体験の説明と実挙動がずれる。
- 本番クライアントへの影響: reviewer/admin 以外が文書を正式根拠化できる場合、根拠文書レビューの
  ガバナンスが成立しない。
- セキュリティ、監査、データ品質、UX への影響:
  - high-risk answer の approved citation gate を、未レビュー文書で満たせる可能性がある。
  - 監査上は「ingest metadata」として残っても、reviewer の明示承認イベントが無い。
  - 文書一覧では approved に見えるため、レビューキューに現れず見落とす。

## どう解決すべきか

1. 実装方針:
   - `/v1/ingest` / internal ingest の単体 upload では、原則として承認状態を server-side policy で
     `pending_review` に正規化する。
   - `approved/imported` を許す場合は、保存済み trusted datasource、または reviewer/admin 以上の
    明示ロールを持つ専用 import path に限定する。
   - body 由来の `approval_status` / `approval_source` / `effective_date` は、信頼済み経路以外では
     safety-relevant metadata として採用しない。
2. UI/UX 方針:
   - `/sources/new` は引き続き `pending_review` を既定にする。
   - reviewer/admin が「承認済みとして取込」を行う必要があるなら、通常 upload と別導線にし、
     監査理由・effective date を必須にする。
3. テスト方針:
   - NestJS e2e または Python integration で、通常 principal が `/v1/ingest` に `approved` を送っても
     `pending_review` に正規化されることを固定する。
   - reviewer/admin または trusted datasource の陽性対照を追加する。
   - high-risk answer が未レビュー ingest 文書で approved citation gate を満たせないことを確認する。
4. 移行や運用上の注意:
   - 既存の `approved/imported` 文書について、review/publish provenance が無いものを棚卸しする。
   - trusted datasource の `approval_policy` は audited config change として維持する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 通常 principal の `/v1/ingest` body だけでは、文書を `approved` / 正式根拠化できない。
- trusted datasource sync は引き続き policy 由来で `approved/imported/effective` を付与できる。
- reviewer/admin が明示承認する場合は、`approval.transition` または同等の監査イベントに actor/reason が残る。
- regression test が追加され、high-risk approved citation gate を未レビュー文書で満たせない。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- フル e-signature / 多段承認ワークフロー。
- datasource trusted policy 自体の廃止。
- demo-only flag での緩和。
- tenant/ACL 仕様の変更。

## 参照

- `apps/api/src/ingest/ingest.controller.ts`
- `apps/answer-service/server.py` (`_mfg_metadata_from_body`, `_mfg_metadata_for_sync`)
- `src/raku_rag/production.py` (`ingest_document`, `attach_manufacturing_metadata`)
- `tests/integration/test_ingest_mfg_metadata_parse.py`
- `issues/0016-document-approval-skip-and-workflow-authz.md`
