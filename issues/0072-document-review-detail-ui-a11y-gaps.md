# 0072 — 根拠文書レビューの詳細確認 UI が抜粋中心で a11y 属性も不足している(系統 = UX / QA / accessibility)

> Priority: **P2 / Medium** / Status: Implemented locally / Labels: `ux`, `qa`, `accessibility`, `document-review`

## 実装結果(2026-07-04)

- source card の `確認する` / `問題だけ見る` に `aria-expanded` / `aria-controls` を付与した。
- 文書詳細は `全文を見る` に変更し、4チャンク以降は「さらに表示」で確認範囲を広げられるようにした。
- `index:` / `source:` などの内部ラベルはデフォルト表示から外し、`管理者向け詳細` の折りたたみに移した。
- stale detail fetch は request token で無視し、別文書を開いた後の古い応答で表示が戻らないようにした。

残る確認: Playwright が入った環境で desktop/mobile screenshot と keyboard 操作を smoke する。

## 背景(なぜ今)

0071 の実装レビューで、根拠文書レビューに `内容確認` 展開と index 完了ガードを追加した。backend 側の承認ガードは安全に寄ったが、UI の詳細確認は先頭チャンク抜粋中心で、承認前レビューとして十分か追加確認が必要になった。

## どんな課題か

- 期待挙動: reviewer は文書単位で十分な本文/チャンクを確認し、展開状態をキーボード/スクリーンリーダーでも把握できる。
- 実際の懸念: `内容確認` は `chunks.slice(0, 4)` の抜粋だけを表示し、残りチャンク数や全文/detail への導線がない。
- 展開ボタンに `aria-expanded` / `aria-controls` がなく、折りたたみ状態が支援技術に伝わりにくい。
- `index:` / `source:` など実装寄りラベルが reviewer の意思決定画面にそのまま出ている。

## どこで起きたか

- 画面: `/reviews/documents` 根拠文書レビュー
- API: `GET /v1/manufacturing/documents/:documentId`
- コード:
  - `apps/web/app/components/FullSaasScreen.tsx` (`DocumentApprovalQueueEnabledBody`, `openDetail`, detail panel)
  - `apps/web/app/globals.css` (`approval-detail-*`)
- 環境: local review。Playwright は未導入でスクリーンショット確認不可。
- run id / ingestion id / correlation id: なし。
- 再現条件:
  1. 5チャンク以上の文書を根拠文書レビューに表示する。
  2. `内容確認` を開く。
  3. 先頭4チャンクのみ表示され、残り確認導線と展開状態の aria が不足していることを確認する。

## 影響

- 営業デモへの影響: 「一件ずつ確認できる」と説明しても、実際は抜粋確認に見え、承認品質の説明が弱い。
- 本番クライアントへの影響: reviewer が全文を確認したつもりで承認し、未確認部分が正式根拠化される可能性がある。
- セキュリティ/安全: backend の index 完了ガードは維持されるが、人間レビュー品質の監査説明が弱くなる。
- UX: raw な `index`/`source` ラベルは運用担当者にとって意味が曖昧。
- アクセシビリティ: 展開状態がスクリーンリーダーへ伝わりにくい。

## どう解決すべきか

1. 実装方針:
   - detail panel に `aria-expanded` / `aria-controls` を追加し、panel id を安定生成する。
   - 5件以上の chunks は「さらに表示」または文書詳細ページへのリンクを出す。
   - 承認ボタンの近くに「確認済みにする」状態を置くか、少なくとも表示範囲が抜粋であることを明示する。
2. UI/UX 方針:
   - `index:` / `source:` を `検索状態` / `同期元` など業務ラベルに置き換える。
   - デフォルトは処理状態と承認判断に必要な情報、詳細は折りたたみ内に寄せる。
3. テスト方針:
   - UI unit/e2e で `aria-expanded`、未表示チャンクの導線、処理中行の承認不可を確認する。
   - API smoke で detail の `chunks` と processing projection が返ることを確認する。
4. 移行や運用上の注意:
   - 既存承認済み文書のレビュー品質棚卸しは別タスク。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- `内容確認` の開閉状態が支援技術に伝わる。
- 抜粋表示の場合、全文/残りチャンク確認への導線がある。
- reviewer 向けの業務ラベルになっている。
- 承認前に表示範囲が明確で、誤って全文確認済みと解釈されない。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- full DMS / e-signature / 多段承認。
- index 未完了文書を承認可能にする緩和。
- 監査ログの raw content 保存。

## 参照

- `issues/0071-document-review-indexing-status-gate.md`
- `apps/web/app/components/FullSaasScreen.tsx`
- `src/raku_rag/manufacturing/app.py`
