# 0046 — File Browser folder persistence gap(系統 = web / product-ux)

> Priority: **P2/Medium** / Status: Open / Labels: `web`, `ux`, `backend`

## 背景(なぜ今)

`/files` を Box 風の直接ファイルアップロード画面として整備する中で、既存 API には
「空フォルダを作成・一覧する」ための tenant-scoped folder/collection API がないことが分かった。
ファイルをアップロードした後のフォルダは `collection_id` から復元できるが、空フォルダや表示名は
ブラウザローカル状態に依存する。

## どんな課題か

- 空フォルダがサーバーに保存されないため、別端末・別ブラウザでは見えない。
- フォルダ表示名をサーバーから取得できないため、文書一覧から復元したフォルダは内部 ID に寄りやすい。
- Box 風 UI としては「作ったフォルダが組織内に残る」ことが期待されるが、現状はファイル投入後に初めて永続化される。

## どこで起きたか

- 画面: `/files`
- API: tenant-scoped folder/collection create/list API が未提供
- コード:
  - `apps/web/app/components/FullSaasScreen.tsx`
  - `apps/web/lib/api-client.ts`
  - `apps/api/src/admin/jobs.controller.ts`
  - `apps/answer-service/server.py`
- 環境: local / AWS sales
- run id / ingestion id / correlation id: なし
- 再現条件: `/files` でフォルダを作成し、ファイルを入れないまま別ブラウザで開く

## 影響

- 営業デモでは、空フォルダの扱いが Box と違って見える。
- 本番クライアントでは、フォルダ作成直後に別ユーザーへ共有できない。
- セキュリティ上はブラウザローカル状態を境界にしてはいけないため、サーバー側で tenant/RBAC/RLS を効かせる必要がある。
- UX 上は内部 `collection_id` が見える可能性が残る。

## どう解決すべきか

1. tenant-scoped `GET/POST /v1/admin/file-folders` または collection metadata API を追加する。
2. フォルダは 1 階層のみとし、parent folder は持たせない。サブフォルダ作成 API は提供しない。
3. folder id と display name を分離し、UI は display name のみを既定表示する。
4. API は signed auth principal の tenant/user/roles から認可し、body tenant override を無視する。
5. `/files` はローカル保存を fallback に留め、サーバー API がある環境では API を SSOT にする。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 空フォルダがサーバーに保存され、別端末でも見える。
- フォルダは 1 階層のみで、サブフォルダを作れない。
- フォルダ表示名が内部 ID と分離される。
- ファイルアップロード時の `collection_id` とフォルダ metadata が一致する。
- tenant/RBAC/RLS 境界を越えないテストがある。

## スコープ外

- 任意階層のフォルダツリー。
- フォルダ単位の独自 ACL。
- 既存承認フローや文書ライフサイクルの緩和。
- demo-only bypass。

## 参照

- `/files` implementation: `apps/web/app/components/FullSaasScreen.tsx`
- Upload ingest DTO: `packages/shared/src/dto/ingest.ts`
- Admin documents facade: `apps/api/src/admin/jobs.controller.ts`
