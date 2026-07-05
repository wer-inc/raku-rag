# 0080 — デプロイの demo-seed がユーザーのアップロードを全消去する(系統 = deploy / demo-seed / data-loss)

> Priority: **P1/High** / Status: Fixed / Labels: `deploy`, `demo-seed`, `data-loss`, `web`, `stg`

## 背景 / 事象

stg で `AK…MD.xlsx`(`manuals` コレクション)をアップロード後、`/files` で「ずっとレビュー待ち」。
実データ調査(Aurora を in-VPC ECS 経由で直接クエリ)で判明:

- アップロード自体は**同期 ingest で成功**していた(`ing_dccc5deadbc00c870138` upload_ingest / succeeded /
  **343 chunks** / 04:45:27→34、7 秒)。xlsx は非同期ではない。
- しかし約 1 時間後の **05:44:37** に document が tombstone=true・全 343 chunks パージ(total_chunks=0)。
  時刻は **0078 デプロイ(`3df1fff`, 05:35→05:45Z)の migrate-seed ステップ**と一致。seed ログに決定的な
  一行: `  succeeded  AK___________MD  purged_chunks=343`。

## 真因

`run_migrate_seed`(deploy.yml、**既定 true**)→ migrate-seed ECS task → `scripts/demo/demo_seed.sh` →
`scripts/demo/demo_seed.py`。旧 `main()` は `purge_ids = existing_ids | curated_ids` を計算し、
**`manuals` コレクションの生存 document を全部** tombstone/purge してから定番 KB(18件)を入れ直していた。
UI アップロードの既定コレクションが同じ `manuals`(`apps/web/lib/session.ts` `DEMO_COLLECTION`)のため、
**デプロイのたびにユーザー投入ファイルが巻き添えで全消去**されていた。

補助的な UI バグ: `/files` はサーバー一覧(tombstone 除外=正しい)に**ブラウザ localStorage の
アップロード記録**をマージ表示する(`FullSaasScreen.tsx` `fileRowsFromDocs`)。サーバーから消えても
localStorage の記録が「レビュー待ち」のまま残り、**幽霊レビュー待ち**として永久表示されていた。

## どう解決したか

1. **`scripts/demo/demo_seed.py`(恒久修正):**
   - `SEED_SOURCE_IDS`(seed 自身が書く source_id = 各 `document_kind` + `case`/`demo`)を導入。
   - `select_purge_ids()` を追加。パージ対象を **curated_ids ∪(source_id が SEED_SOURCE_IDS の生存 seed
     ドキュメント)** に限定。**ユーザーアップロード(`source_id=file-*`)やコネクタ同期は保全**し、保全件数を
     `PRESERVE <id> source_id=...` としてログ出力(監査可能)。
   - `list_existing_collection_docs()` を `{document_id, source_id}` 返却へ変更。
2. **`apps/web`(幽霊レビュー待ちの掃除):**
   - `lib/uploads.ts` に `reconcileIngestedDocs(serverDocumentIds)` を追加。サーバー一覧に無く、かつ
     grace(10分)を過ぎた local 記録を削除(=サーバー側で削除/パージ済み)。
   - `FullSaasScreen.tsx` の `reloadFiles()` で **成功フェッチ時のみ** reconcile(catch では実行しない=
     空と疎通不能を区別できないため)。

## 運用

- ユーザーの実アップロードが存在する間の stg デプロイは、恒久修正の入る前は **`run_migrate_seed=false`** が安全。
  本修正以降は seed=true でもユーザーファイルは保全される。

## どこ

- `scripts/demo/demo_seed.py`(`SEED_SOURCE_IDS` / `select_purge_ids` / `list_existing_collection_docs`)
- `apps/web/lib/uploads.ts`(`reconcileIngestedDocs`)
- `apps/web/app/components/FullSaasScreen.tsx`(`reloadFiles` の reconcile 配線)
- `tests/unit/test_demo_seed.py`(保全不変条件)、`tests/contract/test_web_upload_reconcile.py`(FE マーカー)

## QA checklist

- [x] `tests/unit/test_demo_seed.py`(3 cases)/`tests/contract/test_web_upload_reconcile.py`(3 cases)GREEN。
- [x] Tier A gate GREEN(409)、separation OK、apps/web `tsc --noEmit` 0。
- [ ] stg 反映後: テストアップロード → migrate-seed 実行 → `PRESERVE ... file-*` かつ live chunks 保持を実機確認。

## 受け入れ条件(DoD)

- デプロイ(seed 有効)がユーザーの `file-*` アップロードを消さない。
- サーバーから削除された文書が `/files` に「レビュー待ち」として残り続けない。

## 参照

- memory: deploy-seed-wipes-user-uploads / cloudfront-selffetch-auth-strip
- `issues/0077-…`(アップロード presign 修正)、`scripts/demo/demo_seed.py`
