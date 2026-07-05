# 0081 — ファイル未選択時の「アップロード取込」を常に押せるCTAにする(系統 = web / upload / UX)

> Priority: **P3/Low** / Status: Fixed / Labels: `web`, `ux`, `upload`, `a11y`, `stg`

## 背景

`/files` のアップロードパネルは、ファイル未選択時に「アップロード取込」ボタンを **無効(グレーアウト)**に
していた。無効ボタンは理由も次の行動も語らず、本セッションで繰り返し問題になった「押しても何も起きない」
体感に近い。既に大きなドロップゾーンがあるため、ボタンは“常に意味のある一手”を示すべき。

## どう解決したか(ユーザー選択: 役割を切替/常に押せる)

`FullSaasScreen.tsx` のアップロードCTAを always-actionable 化:

- **未選択**: ラベル「📎 ファイルを選択」。押すと隠しファイル入力(`fileInputRef.current?.click()`)を開く。
- **選択後**: ラベル「⬆ アップロード取込 (N件)」。押すと `onUpload()`。
- **取込中**: 「取込中...」で無効(二重送信防止)。
- 無効化は取込中、または実ブロック時のみ(未選択×権限拒否=選択不可、選択済×ログイン/権限ブロック)。

## どこ

- `apps/web/app/components/FullSaasScreen.tsx`(`fileInputRef` 追加 / `<input ref>` / CTA ボタン)
- `tests/contract/test_web_upload_reconcile.py`(`test_upload_cta_is_always_actionable`)

## QA

- [x] apps/web `tsc --noEmit` 0 / `next build` 成功。
- [x] 契約テスト GREEN(4 cases)。
- [ ] stg 反映後、未選択→「ファイルを選択」で picker が開くことを実機確認。

## 参照

- `issues/0080-deploy-seed-wipes-user-uploads.md`(同 /files 画面)
