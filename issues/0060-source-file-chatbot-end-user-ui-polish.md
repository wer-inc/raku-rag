# 0060 — Source/File/ChatBot画面が運用情報寄りでエンドユーザーの判断が遅い(系統 = web / UX)

> Priority: **P1/High** / Status: Open / Labels: `web`, `ux`, `sources`, `files`, `chatbot`

## 背景(なぜ今)

`/chatbot`, `/sources/*`, `/files` をエンドユーザー視点でより洗練された UI/UX にする依頼があった。
画面を確認すると、同期状態、取込 ID、文書 ID、設定導線など、利用者が最初に判断したい情報より
運用・実装寄りの情報が前に出ていた。

## どんな課題か

- 期待挙動: ユーザーが「今使えるか」「要対応は何か」「次に押すべき操作は何か」を数秒で判断できる。
- 実際の挙動: raw ID や設定・運用情報が主表示に混ざり、状態の読み取りに時間がかかる。
- ソース、ファイル、チャットボットで状態表示の粒度が揃っていない。

## どこで起きたか

- 画面: `/chatbot`, `/sources/list`, `/sources/:sourceId`, `/sources/new`, `/files`
- API: なし(UI表示の情報設計)
- コード: `apps/web/app/components/FullSaasScreen.tsx`, `apps/web/app/globals.css`
- 環境: local / stg 想定
- run id / ingestion id / correlation id: なし
- 再現条件: 対象画面を表示し、状態・次アクション・一覧行の情報優先度を見る。

## 影響

- 営業デモへの影響: UI が運用ツール寄りに見え、プロダクトとしての完成度が低く見える。
- 本番クライアントへの影響: 現場ユーザーが同期や承認状態を誤読し、質問やアップロードに進みにくい。
- セキュリティ、監査、データ品質、UX への影響: ID 表示自体は秘密ではないが、標準表示ではなく詳細に寄せる方が安全で分かりやすい。

## どう解決すべきか

1. Source/File/ChatBot で、状態サマリーと次アクションを主表示にする。
2. raw ID、correlation id、run id は必要な場合だけ折りたたみ・詳細表示へ移す。
3. ファイル・ソース一覧は、検索/絞り込み/状態/レビュー待ち/正式根拠の読み取りを揃える。
4. UI smoke、型チェック、Web build、Tier A で安全ルールが弱まっていないことを確認する。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- `/sources/list` で利用可、要対応、同期中、承認待ちが一目で分かる。
- `/sources/:sourceId` で raw ID より先に利用状態と同期サマリーが見える。
- `/files` でフォルダ数、ファイル数、レビュー待ち、正式根拠の数が見える。
- `/chatbot` で設定寄りの表現より、利用状態と回答前提が分かる。
- 既存の ACL、承認済み根拠、source policy、fail-closed の挙動を弱めていない。

## スコープ外

- 新しい API の追加。
- RAG 回答品質そのものの変更。
- 管理者専用ダッシュボードの再設計。
- Playwright テスト基盤の新規導入。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx`
- `apps/web/app/globals.css`
- `issues/0059-chatbot-sidebar-user-admin-info-mixing.md`
