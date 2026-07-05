# 0084 — アップロード document_id を UUID にする(系統 = web / upload / IDs)

> Priority: **P2/Medium** / Status: Fixed / Labels: `web`, `upload`, `ids`, `stg`

## 背景

アップロードの `document_id` は**ファイル名由来の slug**(`documentIdForUpload`→`cleanDocumentIdPart`)だった:

- 同名ファイルを2回アップロード → **同じ document_id → 後のが前を上書き**(サイレント衝突。フォルダ違いでも
  `(tenant, document_id)` で引くため衝突)。
- 全日本語名は slug が空 → `doc-<timestamp>` にフォールバック(人が読めず、ミリ秒衝突もあり得る)。
- URL / fallback 表示に mangled な id(`AK___________MD` 等)が露出。

0083 で**実ファイル名を display_title として保持**するようにしたので、id を人間可読にする必要は無くなった。

## どう解決したか(ユーザー選択: 純UUID)

- `documentIdForUpload()` を `crypto.randomUUID()` を返すだけに変更(引数廃止)。
  - 呼び出し2箇所(ファイルアップロード / テキスト貼り付け)を更新。
- **表示は常にファイル名**(一覧・詳細は `filename` / `display_title`。0083)。ユーザーは生のUUIDを読む必要がない
  (Google Drive 等と同じ「不透明ID + 可読な表示名」)。
- 効果: 同名アップロードの上書き衝突が消える / id が一意で安定 / URL にファイル名由来の文字列が出ない。
- 影響範囲: **新規アップロードのみ**。既存ドキュメントの id は不変。

## どこ

- `apps/web/app/components/FullSaasScreen.tsx`(`documentIdForUpload` + 呼び出し2箇所)
- `tests/contract/test_web_upload_reconcile.py`(`test_upload_document_id_is_an_opaque_uuid`)

## QA

- [x] `tsc --noEmit` 0 / `next build`(eslint 含む)成功 / 契約テスト GREEN。
- [ ] stg 反映後、アップロード→URL が UUID・一覧表示はファイル名、同名2回で別ドキュメントになることを実機確認。

## 参照

- `issues/0083-japanese-filename-preserved-in-files.md`(display_title=ファイル名)
