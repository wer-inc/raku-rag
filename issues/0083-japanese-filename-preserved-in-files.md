# 0083 — アップロードした日本語ファイル名が /files で `___` になる(系統 = web / upload / i18n)

> Priority: **P2/Medium** / Status: Fixed / Labels: `web`, `upload`, `i18n`, `answer-service`, `stg`

## 事象

日本語名のファイルをアップロードすると、`/files` の一覧で `AK___________MD.xlsx` のように**日本語が全部 `_` に化ける**。

## 原因

1. **直接原因 — `safeFilename`(`apps/web/app/api/upload/presign/route.ts`)**
   `(rawName).replace(/[^A-Za-z0-9._-]/g, "_")` で **ASCII 以外(日本語)を全部 `_` に置換**していた。
   S3 のオブジェクトキーは `randomUUID()` で作られ**ファイル名は使わない**ので、この ASCII scrub は不要で、
   表示名を壊すだけだった。この値が localStorage / アップロード provenance レコードに保存され表示される。
2. **二次的ギャップ — サーバーに元ファイル名が残らない**
   ingest 時に元ファイル名が Document に保存されず、`/files` のサーバー行は `document_id`(これも記号化)を
   表示。→ 再読込・別ブラウザだと日本語名が失われる。

## どう解決したか(A+B)

- **A**: `safeFilename` を「Unicode 文字(日本語)は保持、危険文字(制御文字・パス区切り・`:*?"<>|`)だけ
  除去」に変更。表示専用なので日本語を保てる。
- **B(サーバー永続 + 表示)**:
  - `production.py ingest_document` に `filename` を追加し、成功時 `doc.metadata["filename"]` に保存
    (同期・画像・PDF stub の各経路)。
  - `apps/answer-service` の `/internal/ingest` が **upload provenance レコードの filename**(無ければ body の
    filename)を `ingest_document(filename=...)` に渡す。→ サーバー権威の元名が Document に残る。
  - `_document_display_title`(既存)が `metadata["filename"]` を拾い `list_documents` の `display_title` に。
  - `/files` の**サーバー行が `display_title`** を使う(`filename: doc.display_title || doc.document_id`)。
  → アップロード直後(localStorage)・再読込・別ブラウザのいずれでも日本語名を表示。

## どこ

- `apps/web/app/api/upload/presign/route.ts`(`safeFilename`)
- `src/raku_rag/production.py`(`ingest_document` / `_upsert_pending_document_stub` の `filename`)
- `apps/answer-service/server.py`(`/internal/ingest` が upload_record.filename を渡す)
- `apps/web/app/components/FullSaasScreen.tsx`(サーバー行 `display_title`)
- tests: `tests/unit/test_production_ingest_document.py`、`tests/contract/test_upload_presign_route.py`、
  `tests/contract/test_web_upload_reconcile.py`

## QA

- [x] Tier A GREEN(409)/ 契約・ユニット GREEN / `tsc` 0 / `next build` 成功 / black+ruff clean。
- [ ] stg 反映後、日本語名アップロード→`/files` で日本語表示、再読込でも保持、を実機確認。

## 参照

- `_document_display_title`(`src/raku_rag/manufacturing/app.py`)、`UploadRecord.filename`
