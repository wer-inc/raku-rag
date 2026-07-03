# UI/UX 監査 — 全画面の機能棚卸しと改善点(★U, 2026-07-03)

apps/web 全画面をコードレベルで監査(3方面並列: 回答体験 / 運用系 / 電話・チャット・シェル)。
全指摘 file:line 根拠付き。分類: **[デモ映え]**=商談5分で見える / **[日常運用]** / **[磨き]**。
既知 issue(0010-0022 承認UX、0025-0032 チャットボット、0038/0040/0060)と突合済み。

## 総評

**基盤は本物、仕上げが不均一。** トースト(種別別role/duration)・useDialogフォーカストラップ・
RBAC nav・:focus-visible・reduced-motion・mock/実測の正直な出し分け(代理値表記)・権限シミュ
レーターは製品級。チャットボット画面が最も洗練されている一方、**旗艦の回答画面と営業ショー
ピースの電話画面ほど仕上げが弱い**。ほぼ全ての改善は「チャットボットに既にあるパターンの
横展開」で済む(再設計不要)。CSSは実質2枚のスタイルシート連結(重複セレクタ47件)が構造リスク。

## 構造的発見(最重要2点)

1. **運用/管理の差別化画面が nav に存在しない**(lib/full-saas.ts:73-92)。manifest には
   operations 7画面 + admin 10画面が定義済みなのに、品質KPI・改善キュー・監査ログ・ロール/
   ACL・権限シミュレーターへ辿る nav 項目が無い(直URLのみ)。「運用できるRAG」の証拠が全部埋没。
2. **回答画面が Markdown 未レンダリング**(FullSaasScreen.tsx:749-750 が `<p>{r.text}</p>`、
   `.answer-text` に pre-wrap も無し)。Bedrock の `**強調**`・箇条書き・表が生記号のまま出る。
   チャットボットには ChatMessageMarkdown(:1125-1145)が既にある。

## [デモ映え] 指摘(抜粋・優先順)

| # | 工数 | 根拠 | 内容 |
|---|---|---|---|
| U1 | S-M | :749, globals.css:2772 | 回答本文の Markdown レンダリング + pre-wrap(ChatMessageMarkdown 再利用) |
| U2 | M | :980 | 回答生成中が13pxグレー1行。チャットの ChatThinkingBubble(:1079)を移植(2-9秒の最注目時間) |
| U3 | S | globals.css:6570 | 電話AIの5タブが全部同一の紫ボタン、`[aria-selected]` スタイル皆無 — アクティブタブ不明 |
| U4 | M | :2260-2290 | 通話シミュレータの会話ログが素の `顧客:/AI:` 段落。吹き出し・話者レーン・レイテンシバッジ化(通話履歴側:2519には良い表が既にある) |
| U5 | S | :2188,2271,2494 | 電話フローに生enum/ID露出(`completed(call_…)`、document_id/chunk_id/score) |
| U6 | S | :179-196,9560 | 請求/ユーザー/連携が**mock表示なしの偽データ**(架空インボイス"INV-2026-05 paid"等)。「サンプル」バッジ必須 |
| U7 | S | onboarding/page.tsx:22-42 | 初回導線のチップが押せない飾り+「ステップ1/3」詐称 |
| U8 | M | full-saas.ts:73-92 | 「運用」「管理」navグループ追加(構造的発見1の解消) |
| U9 | S | :7917 | **GDrive OAuthコネクタが実装済みなのにUI非表示**(readinessフィルタで死蔵)。他コネクタも「対応予定」disabled表示で網羅性訴求 |
| U10 | M | :5406-5416 | 品質評価セクションが「実行」押下まで白紙。前回結果/合否ゲートを既定表示 |
| U11 | S | :5108-5132 | ドラフト生成フォーム初期値が生ID(`m1`)でプロトタイプ感 |

## [日常運用] 指摘(抜粋)

| # | 工数 | 根拠 | 内容 |
|---|---|---|---|
| U12 | S | :224-230 | エラーが生 `HTTP 502` のまま表示(日本語化は failed to fetch のみ)。+ AbortController タイムアウト/リトライ無し(:899) |
| U13 | S | full-saas.ts:34 | 承認ワークフローが既定OFF(看板のガバナンスUI一式が休眠)。demo では既定ON推奨 |
| U14 | M | :5661-5776 | 改善キューが3リスト縦積み(server/監査/localStorage)で重複・状態管理非対称。単一server駆動に統合 |
| U15 | M | :8064-8075 | Add Source にフィールド必須検証なし(bucket空でも保存試行→backendエラー頼み)。collection_id も manuals 固定(:7524) |
| U16 | S | :2825,2314 | 電話シナリオの公開/ロールバック・転送受理が確認ダイアログなし(ConfirmDialogパターンは:4893に既存) |
| U17 | S | full-saas.ts:86 vs :2969 | 用語ゆらぎ: nav「外部接続」vs タイトル「ソース」(他: 取込ラン/取り込み実行) |
| U18 | S | :5084 | レビューバッジが定数`2`固定(full-saas.ts:41)、キュー件数もstatus無視の全件 |
| U19 | M | :911-914 | 回答画面はスレッド見た目なのに毎回文脈なし送信(追い質問が独立質問になる) |

## [磨き] 指摘(抜粋)

- 生 retrieval_score の露出(CitationViewer:178, :830 — issue 0040 DoD残)/ collection selector が生ID(:992)
- CitationViewer「有効期限/発効」ラベルが effective_date しか出さない(0017のvalid_until未表示)/ PDF iframe 280px固定
- 検索画面に ops 診断(run ID手入力)が同居(:1891)/ プレースホルダが回答画面と同文(:1841)
- 管理系の生JSONダンプ(検索設定:9516、監査:9093)/ APIキー画面が空でCTA無し(:9547)
- CSS: #a1a1aa がAAコントラスト不合格(~24箇所)/ 重複セレクタ47件 / spacing トークン未活用 / ダークモード無し
- ScreenShell にパンくず/戻るが無い(:3013)/ 🎤絵文字ボタン / 履歴「再質問」が自動送信しない(:4161)

## 回帰させない強み

権限シミュレーター(:9118)・エビデンスパックのチェーン検証✓表示(:5482)・代理値/実測の明示
(:5367)・No-train整形(:9268)・ソース一覧の状態+復旧導線(:3134,:3208)・ログイン画面・トースト。

## 推奨実装パッケージ(順)

1. **P1 回答体験(U1+U2+U12)** — 旗艦画面のMarkdown/ローディング/エラー日本語化。工数~1日
2. **P2 電話ショーピース(U3+U4+U5+U16)** — タブ選択状態/吹き出しトランスクリプト/enum日本語化/確認ダイアログ。~1日
3. **P3 見せ場の解放(U8+U13+U6+U9+U10)** — nav再構成/承認フロー既定ON/mock正直化/GDrive露出/品質既定表示。~1-2日
4. **P4 運用の完成度(U14+U15+U17+U18+U11)** — 改善キュー統合/フォーム検証/用語統一。~2日
5. **P5 衛生(CSS重複解消+コントラスト+磨き群)** — ~2日

## 実装状況

- [x] 本監査ドキュメント
- [x] P1 回答体験(U1+U2+U12)
- [x] P2 電話ショーピース(U3+U4+U5+U16) — `.screen-tabs` タブ選択状態 / `.phone-transcript-*` 吹き出しトランスクリプト / `PHONE_LABELS` enum日本語化(生値はtitle属性に退避) / 公開・ロールバック・転送受理の ConfirmDialog
- [x] P3 見せ場の解放(U8+U13+U6+U9+U10)
  - U8: NAV_GROUPS に「運用」(運用ダッシュボード/品質・KPI/改善キュー/安全テレメトリ/導入効果レポート/監査ログ)と「管理」(ロール・権限/プロバイダポリシー/ユーザー/連携/請求/検索設定/ログポリシー)を追加。RBAC は manifest 準拠(nav-rbac: ops_owner に /audit、reviewer に /operations/improvements を追加付与)。両グループは `defaultCollapsed` でサイドバー折りたたみ(アクティブルート内包時は自動展開)
  - U13: `APPROVAL_WORKFLOW_ENABLED` 既定 ON(`NEXT_PUBLIC_RAKU_APPROVAL_WORKFLOW=off` で無効化)。レビュー nav / 承認待ち列 / DocumentApprovalQueue / ApprovalWorkflow が既定表示(いずれも実エンドポイント + 空状態確認済み)
  - U6: 請求(BillingBody)・ユーザー・連携(MockAdminScreen)に「サンプルデータ」バッジ+準備中の説明(`.sample-data-notice`)。onboarding はステップ詐称を廃止し単一ステップ「利用目的を選ぶ(任意)」に変更、チップは実選択(localStorage `raku.onboarding.preferences` に保存)
  - U9: Add Source のコネクタグリッドが全13種を表示(ready のみ選択可、three_days/later は disabled +「近日対応/ロードマップ」バッジ)。Google Drive は readiness=ready に昇格(実装済み OAuth フローが到達可能に。未設定時は authorize が not-configured エラーを返し UI が接続エラー表示)
  - U10: 品質評価セクションがマウント時に前回の永続化 run を既定表示(タイムスタンプ+ゲート判定、「再実行」ボタン)。API に `GET /v1/evaluations/latest`、answer-service に `GET /internal/evaluations/latest` を追加し、evaluation_runs リポジトリを Postgres 永続化に配線(再起動を跨いで表示されることを実PGで確認)
- [x] P4 運用の完成度(U14+U15+U17+U18+U11)
  - U14: 改善キューを 1 リストに統合(ImprovementQueueBody)。由来チップ(フィードバック=GET /v1/feedback / 監査=GET improvements / この端末=localStorage)+新しい順ソート+由来・対応状況フィルタ。重複排除は `answer_id` を結合キーに(local 行は feedback_id/correlation_id を保持しないため answer_id が両者共通の唯一のキー)、server 行に一致した local 行は畳み込み、その 対応済み/未対応 状態とトグルを server 行に引き継ぐ(状態はこの端末のみ保存と明記)。「この一覧を消去」(全消去)は「対応済みをまとめて消去」(resolved の local 行のみ削除、ConfirmDialog 付き)に置換。**フォローアップ**: server 行(フィードバック/監査)の対応状態を永続化する server-side resolve API は未実装(スコープ外として据え置き)
  - U15: コネクタ定義に `required` フラグを追加(answer-service の datasource_sync 要求と同一: URL→target_url / S3→bucket / DB→connection_string+table_name / kintone→subdomain+api_token+app_id / Confluence→site_url+space_key+email+api_token / Notion→database_id+integration_token / Box→access_token / GDrive は OAuth 接続ゲートのまま)。クライアント側検証: 必須未入力はインライン `field-error` + aria-invalid + 先頭の invalid へフォーカス、保存/接続テスト/同期をブロック(backend エラーは最終網として維持)。回答範囲(コレクション)select を追加(text/コネクタ両フォーム、既定 manuals、選択肢は Answers 画面と同じ adminDataSources 由来)
  - U17: 用語統一 — screenTitle: source-list「ソース」→「外部接続」/ source-detail→「外部接続の詳細」/ add-source→「外部接続を追加」/ source-search→「検索」/ ingestion-runs「取り込み実行」→「取込履歴」。CTA「ソースを追加」→「外部接続を追加」(AddSourceCta・空状態リンク・ホームカード)、AddSource 見出し「ソース種別」→「外部接続の種別」、取込ラン/取り込み実行の表記→「取込履歴」(ボタン・メトリクス・検索診断パネル)。「ファイル」アップロードは従来どおり別概念。コード識別子・route は不変更(ラベルのみ)
  - U18: `REVIEW_BADGE_COUNT`(固定 2)を削除し、Sidebar が既存 `GET drafts`(manufacturingListDrafts)から pending(status=draft/in_review)件数を取得(マウント時+ /reviews への route 遷移時のみ、ポーリング無し、エラー時はバッジ非表示)。ReviewQueueBody は全件カウントをやめ、未対応バブル+ステータス別内訳(下書き/レビュー中/承認済み/却下)を表示
  - U11: ドラフト生成フォームの生 ID 入力(`m1` 既定)を廃止し、実ドキュメント一覧(manufacturingDocuments + ローカルアップロードの filename で表示名を補完)からのチェックボックス複数選択に置換。「詳細指定(ID を直接入力)」トグルでフリーテキスト入力へフォールバック可。コレクションは select 化(既定 manuals)
- [x] U19 追い質問の文脈維持(回答スレッドの文脈引き継ぎ)
  - Web: AnswersBody が送信ごとに直近≤5往復の `{question, cited_document_ids}` を `history` として送信。サーバーが照応追い質問を書き換えた場合は回答カードのサマリー帯に「文脈を引き継ぎました」チップ(title に実際の検索クエリ)を表示
  - API: `/v1/manufacturing/answer` に optional `history` をパススルー(テナントは従来どおり principal から)。共有 DTO に `AnswerHistoryTurn` / `context_carried` / `retrieval_query` を追加、OpenAPI 更新
  - answer-service: `/internal/manufacturing/answer` が `history`(most recent last、サーバー側で5件に cap)を受理。チャットボット L2 の照応解決ロジックを `src/raku_rag/core/coreference.py` に共有化(chatbot/coreference.py は委譲、挙動バイト同一・既存テスト無修正)し、書き換えた standalone クエリで検索しつつ **生の追い質問を `intent_query` として通線**(高リスク分類と承認済み引用要件は常に生クエリに束縛 — チャットボットと同じ安全不変条件)。history 無し/非照応クエリは従来とバイト同一
  - 安全証明: tests/unit/test_answer_followup_context.py(P-101 トルクの良性シナリオが正しい引用で回答/「その圧力の抜き方」系が生テキストから高リスク分類され approved_citation_missing でブロック/intent 落としの再現ピン/承認済み時の陽性対照/history 無しバイト同一)+ tests/integration/test_answer_followup_endpoint.py(HTTP 境界の配線)
- [x] P5 衛生(CSSコントラスト+重複解消+磨き群)
  - コントラスト(AA): 小さめ二次テキストの `color: #a1a1aa`(白地で2.6:1、AA不合格)20箇所を既存トークン `var(--muted)`(#666b78、5.3:1)へ置換。**据え置き(意図的)**: disabled ボタン文字の #a1a1aa×1 / #8b90a0×2(WCAG 1.4.3 は非活性UIを適用除外、無効状態の見た目の区別を維持)、`background`/`border-color` の #a1a1aa 各1(テキストでない)。他のAA不合格テキスト色は残存なし(#ffffff は着色背景上のみ)
  - CSS重複解消(保守的パス): 完全に上書きされていた先行の死にルール15件を削除(`body`/`.sidebar`/`.nav-item:hover`/`.error-panel` 等 — 同一セレクタの後続宣言がプロパティ上位集合のため計算スタイル不変)。3つの `:root` トークンブロックを先頭の1つに統合(和集合・後勝ち、37トークン。値の衝突は無し)。プロパティが分散する残り25組の重複セレクタは**削除せず** `/* NOTE: extended in ... section below */` コメントを先頭出現箇所に付与(完全統合はリスクありとして見送り)。検証: tsc / next build(PostCSSパース)クリーン
  - 磨き1: CitationViewer の生スコアチップを廃止し、種別チップの `title` 属性に退避(運用診断用)。回答画面の引用カードは既に `診断情報` details 内のため変更なし。Answers の参照範囲セレクタが生IDだった箇所に `collectionDisplayName` を適用
  - 磨き2: 「有効期限 / 発効」→「発効日」に是正(回答パスの citation ペイロードは valid_until を未搬送)。Citation DTO に optional `valid_until` を追加し、値が来た場合のみ「有効期限」行を表示(型のみの前方互換、バックエンド変更なし)
  - 磨き3: PDF プレビュー iframe 280px→480px、blob URL があるとき「新しいタブで開く」リンクを追加
  - 磨き4: 検索画面の ops 診断(source_id/run_id 照会)を折りたたみ `<details>`「運用診断(上級者向け)」へ移動。プレースホルダを回答画面と差別化(「症状・キーワードで検索する…」)。生トークンを日本語化(equip→設備 / process→工程 / case→事例)。relevance_score は number 型ガード付きで表示
  - 磨き5: ScreenShell に「← 戻る」(router.back())を追加 — source-detail / document-detail / review-detail の詳細系3画面のみ表示
  - 磨き6: 履歴「再質問」が `/?q=…&submit=1` で自動送信(保存済み参照範囲で送信、送信後は URL パラメータを除去しリロード再送信を防止)。`submit=1` なしの `?q=` は従来どおりプリフィルのみ
  - 磨き7: 🎤 絵文字は**維持**(アプリにアイコンシステムは無くアドホックなインラインSVGのみ、マイク字形も既存に無し)。絵文字を `aria-hidden` 化しスクリーンリーダーにはテキストのみ読ませるよう改善
