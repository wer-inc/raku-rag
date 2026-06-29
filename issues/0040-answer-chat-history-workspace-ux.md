# 0040 — 回答・チャット・履歴が業務ワークスペースとして分断して見える(系統 = ux / frontend)

> Priority: **Medium** / Status: Open / Labels: `ux`, `frontend`, `answers`, `chatbot`

## 背景(なぜ今)

`質問する`、`チャットボット`、`回答履歴` の画面を SaaS の主要利用導線として確認したところ、回答の根拠、安全状態、次の操作、履歴再利用が画面ごとに分断されて見えることが分かった。

## どんな課題か

- `質問する` は回答生成そのものはできるが、空状態や回答後の次アクションが薄く、根拠不足や安全保留からどこへ進むべきかが分かりにくい。
- `チャットボット` は raw session id や raw state が目立ち、業務ユーザー向けの会話状態より実装状態に見える。
- `回答履歴` は localStorage の暫定履歴だが、一覧だけでは監査ログや tenant-wide 履歴と誤解されやすく、検索・再質問・消去確認も不足している。

## どこで起きたか

- 画面: `/`, `/chatbot`, `/answers/history`
- API: 変更なし
- コード: `apps/web/app/components/FullSaasScreen.tsx`, `apps/web/lib/answer-history.ts`, `apps/web/app/globals.css`
- 環境: local repository UX review
- run id / ingestion id / correlation id: none
- 再現条件: 3画面を空状態、回答後、チャット開始後、履歴保存後の状態で確認する。

## 影響

- 初回ユーザーが「何を質問できるか」「どの根拠を参照しているか」を判断しにくい。
- 安全保留や根拠不足のとき、文書承認や追加へ進む導線が弱い。
- 履歴がローカル保存であることが弱く、監査ログとの役割差が曖昧になる。
- デモや日常利用で、質問、チャット、履歴の価値が別々の機能に見える。

## どう解決すべきか

1. `質問する` はサンプル質問、参照範囲、根拠不足時のレビュー導線、診断情報の控えめ表示を追加する。
2. `チャットボット` は会話状態を業務ラベルへ置き換え、スターター、新しい会話、人間引き継ぎ、参照範囲を分かりやすくする。
3. `回答履歴` はこのブラウザの最近の回答として明確化し、検索、状態/安全フィルタ、回答抜粋、再質問、消去確認を追加する。
4. API 契約と安全境界は変更せず、UI と localStorage helper の互換拡張に閉じる。

## QA checklist

- [ ] `質問する` の空状態、回答カード、根拠不足/安全保留導線が確認できる。
- [ ] `チャットボット` の初回、継続、遅延、人間引き継ぎ状態が確認できる。
- [ ] `回答履歴` の検索、フィルタ、再質問、消去確認が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Web build/typecheck または同等の frontend verification が通る。

## 受け入れ条件(DoD)

- 3画面が回答利用ワークスペースとして一貫して見える。
- localStorage 履歴がローカル暫定保存であることを画面上で説明できる。
- raw id / raw state / retrieval score がデフォルトの主要情報として目立たない。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- 回答履歴のサーバ永続化。
- 公開チャット widget / external anonymous access の設定 UI。
- ChatBot source exposure policy API の変更。
- security/safety の緩和や demo-only bypass。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx`
- `apps/web/lib/answer-history.ts`
- `issues/0026-chatbot-p0-response-ux-without-websocket.md`
- `issues/0027-chatbot-datasource-exposure-policy.md`
- `issues/0029-chatbot-source-policy-pre-rag-filter-gap.md`
