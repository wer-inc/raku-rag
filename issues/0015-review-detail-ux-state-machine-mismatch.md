# 0015 — レビュー詳細の操作が状態機械とズレ／重複・確認/二重送信なし(系統 ①②)

> Priority: **P2 / Medium** / Status: Open / Labels: `frontend`, `ux`, `review`, `a11y`, `safety-critical`

## 背景(なぜ今)

レビュー詳細(`ReviewDetailBody`)と文書承認キュー(`DocumentApprovalQueueBody`)は、規制系の
**不可逆な承認操作**を行う画面。だが UI がバックエンド状態機械とズレた操作を提示し、確認も二重送信防止も無い。
誤承認・誤却下のリスクと操作不能のフリクションが同居している。

## 現状(根拠 / 各サブ課題)

1. **承認ボタンが draft 状態でも活性** — `FullSaasScreen.tsx:2143` の「承認・公開」は `terminal` 以外で常時活性。
   だが backend は承認に `in_review` 前提を要求(`drafts/review.py:101-119`)。作成直後(draft)に押すと
   `InvalidTransitionError`(→409)。「先に担当割当」を促すガイドが無い。
2. **二重送信ガード無し** — `onAssign`(`:2004-2015`)/`onReview`(`:2017-2030`)に saving フラグ無し。ボタンは
   `terminal` でしか無効化されず、POST + 再取得の最中も活性 → ダブルクリックで重複 POST。create フォームは
   `creating` で守られている(`:2230,2316`)のに承認系は未対応。
3. **確認ダイアログ無し** — 承認/却下/旧版化はワンクリックで監査付き不可逆遷移。confirm が一切無い
   (`:2143-2148`, 文書側 `:1953-1968`)。
4. **却下理由が任意** — `onReview` は `comment.trim() || undefined`(`:2022`)、textarea も「(任意)」。
   理由ゼロで AI ドラフトを却下可能(監査・HR5 の意図と乖離、→[0018](0018-approval-audit-trail-gaps.md))。
5. **不正遷移を選択肢として提示** — レビュー詳細内の「文書承認」ミニフォーム(`:2153-2166`)が
   `draft`/`pending_review` への**後退**を select で提示(`:2156-2161`)。backend は前進専用で弾く
   (`ingestion/approval.py:190-201`)。さらに自由入力 `document_id`、成功フィードバック無し
   (`onApproveDocument` はエラー時のみ反映 `:2032-2040`)。文書承認キューと重複し混乱。
6. **担当者が自由入力＋既定 "alice"・自己レビュー警告無し** — `:1984` 既定 "alice"、`:2129` 自由入力。
   ログイン者と無関係に既定。実在レビューアの選択肢も自己レビュー警告も無し。
7. **承認/旧版化に発効日・確認・理由が無い(文書側)** — `DocumentApprovalQueueBody`(`:1851-1980`)。
   承認は「質問の正式な根拠になる」(`:1926`)安全クリティカル操作なのに、確認・理由・発効日入力が無く、
   backend が `effective_date=today` を自動押印(`ingestion/approval.py:96-101`)= 未来発効/正しい発効日を
   UI から設定できない。
8. **生の status 値が日本語 UI に露出** — 「決定」行 `draft.approval_decision ?? "—"`(`:2091`)を未ローカライズで表示。
9. **ローディング状態欠如(両キュー)** — 初期 `[]` のため「まだドラフトはありません」/「取り込んだ文書がありません」が
   先に一瞬出てから一覧に差し替わる(`:2273-2276`, `:1928-1931`)。詳細画面は実装済み(`:2042`)。
10. **アクセシビリティ** — キュー行は `<Link>` が無ラベルの `<span>` 群を内包し SR が一続きに読む(`:2282-2287`)。
    エラー/成功の role が不統一(`role="alert"` `:2320` と `aria-live="polite"` `:884`、文書側 `:1975/1976`)。

## 提案作業(何をどう対応)

- **(1)** 「承認・公開」を `draft.status === "in_review"` のときだけ活性化。draft のときは「先に担当者を割り当て」
  のインライン誘導を表示。
- **(2)** 各操作に `saving` フラグを設け、POST 中は assign/approve/reject を一括無効化(create と同様)。
- **(3)** 承認・却下・旧版化に確認ステップ(モーダル or 二段クリック)。不可逆である旨を明記。
- **(4)** `decision==="rejected"` のとき comment 必須(空ならボタン無効/バリデーション)。
- **(5)** レビュー詳細内の埋め込み「文書承認」フォームを**削除**して `/reviews/documents` へ誘導。残すなら
  現在状態から**前進方向のみ**に option を制限＋成功フィードバック＋一覧リフレッシュ。
- **(6)** 担当者を**ユーザー/グループのピッカー**に置換(ディレクトリ由来)。既定は未割当(="alice" をやめる)。
  ログイン者=作成者/担当のとき自己レビュー警告。※ ピッカーの母集合が無いので reviewers 取得 API が必要
  (現状エンドポイント無し。暫定は既知ユーザー、本番は要 API)。
- **(7)** 承認時に**発効日入力**(任意で未来日)＋レビューコメント欄を文書承認キューにも追加。`effective_date` を
  リクエストで送れるようにする(backend 側の自動押印は未指定時のみ)。
- **(8)** `approval_decision` を日本語ラベル表に通す(`draftStatusLabel` と同様)。DTO の値ドリフト
  (`approve|reject` vs `approved|rejected|archived`)も整合(→[0018](0018-approval-audit-trail-gaps.md))。
- **(9)** 両キューに loading 状態(スピナー/スケルトン)。初回 fetch 確定後にのみ empty を表示。
- **(10)** 各行 `<Link>` に説明的 `aria-label`(例「ドラフト <id> · <種別> · 状態 <status> · 担当 <reviewer>」)。
  成功=`role="status"`/`aria-live="polite"`、エラー=`role="alert"` に統一。

## 受け入れ条件(DoD)

- [ ] draft 状態のドラフトで「承認」できない(UI 上不可、エラー誘発しない)。
- [ ] 承認/却下/旧版化は確認後にのみ実行、却下は理由必須。
- [ ] 連打で二重 POST されない。
- [ ] UI が提示する遷移は全て backend で合法(後退選択肢が無い)。
- [ ] 承認時に発効日を設定できる。生の英語 status が表示されない。両キューに loading。

## スコープ外

- 通知/SLA/担当インボックスは [0013](0013-review-badge-and-list-staleness.md) と queue robustness。承認後の公開は [0019](0019-no-publish-path-after-approval.md)。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx:1851-1980,1984,2004-2040,2091,2129,2143-2167,2153-2166,2271-2291`
- `src/raku_rag/manufacturing/drafts/review.py:101-119`, `src/raku_rag/manufacturing/ingestion/approval.py:96-101,190-201`
