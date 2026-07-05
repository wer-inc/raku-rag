# 0078 — 画面に入ると「戻る」が無く、メニューから再入するしかない(系統 = web / navigation / UX)

> Priority: **P1/High** / Status: Fixed / Labels: `web`, `ux`, `navigation`, `a11y`, `stg`

## 背景(なぜ今)

「frontend 全体的にメニューに入って back ができない。また menu から再度入って確認することになる」
と報告された。特にモバイルではサイドバーがドロワーのため、画面に入ると戻る手段が実質ドロワー再オープン
＋再タップしかなかった。

## どんな課題か(監査で確定した gap)

- 全 35 画面のうち **戻るボタンがあるのは 3 画面のみ**(`source-detail` / `document-detail` /
  `review-detail`、`ScreenShell` 内の `BACK_AFFORDANCE_SCREEN_IDS`)。他は in-app 戻る導線ゼロ。
- **モバイルヘッダは hamburger + "Raku RAG" のみ**で戻る/パンくず/現在画面名なし。
- `ScreenShell` の `router.back()` は**無条件**。deep-link / ハードリロード後に押すと**アプリ外へ出る**
  か何も起きない(親ルートへの fallback が存在しない)。
- サイドバー未掲載の孤立画面(`/documents`, `/answers/history`, `/ingestion-runs`,
  `/compliance/export`, `/admin/api`, `/admin/support`, `/admin/retrieval/debug`)は戻る手段皆無 →
  メニューからすら再入不能。
- 状態ベースの詰まり: Phone 転送キュー詳細 / 通話履歴詳細に閉じるボタンなし。add-source の種別選択
  ステップに一覧への戻りなし。

## どう解決したか(スコープA: 全画面に戻る + 詰まり解消)

1. **全画面に信頼できる「← 戻る」**(root = `answers` / `home-dashboard` を除く全画面、`ScreenShell`)。
   - `lib/nav-history.ts`: `noteInAppNavigation()` / `canGoBackInApp()`。full page load で 0 にリセット。
   - `AppShell`: 初回マウントを除く in-app ルート変更ごとに `noteInAppNavigation()`。
   - 戻る動作: **in-app 履歴があれば `router.back()`(元の画面に正確に戻る)、無ければ親ルートへ
     `router.push()`**(`SCREEN_PARENT_HREF`、既定 `/home`)。deep-link / リロードでも dead-end や
     アプリ外脱出をしない。孤立画面も親を持つ。モバイルでも同じヘッダの戻るで機能。
2. **詰まり解消**: Phone 転送キュー詳細/通話履歴詳細に「← …に戻る」閉じるボタン(`detail-back-row`)。
   add-source 種別選択の一覧戻りは①の全画面戻る(`add-source → /sources/list`)で解消。
3. **a11y/モバイル**: `.topbar-back:focus-visible` アウトライン、モバイル(≤900px)でタップ領域拡大
   (min-height 40px)。

## どこ

- `apps/web/lib/nav-history.ts`(新規)
- `apps/web/app/components/AppShell.tsx`(nav 計測)
- `apps/web/app/components/FullSaasScreen.tsx`(`ScreenShell` 全画面戻る + `SCREEN_PARENT_HREF` +
  Phone 詳細の閉じる)
- `apps/web/app/globals.css`(`.detail-back-row` / focus / モバイルタップ領域)
- `tests/contract/test_web_back_navigation.py`(新規、source-level 契約)

## QA checklist

- [x] 再現/固定テストがある(source contract 5 cases / 15 subtests)。
- [x] typecheck + `next build` 成功。
- [x] Tier A gate GREEN。
- [x] tenant/ACL 境界を越えない(表示のみ、RBAC の `AccessDenied` は不変更)。
- [x] security/safety gate を弱めていない。
- [ ] stg 反映後にモバイル/デスクトップで戻る導線を実機確認。

## 受け入れ条件(DoD)

- root(ホーム/回答)以外の全画面に「← 戻る」がある。
- in-app 履歴があれば元画面へ、無ければ親ルートへ戻る(アプリ外に出ない)。
- Phone 詳細サブビューが閉じられる。
- 既存の RBAC / 安全 / 監査要件を弱めていない。

## スコープ外(今回)

- パンくず(クリック可能な祖先パス)。
- 状態ドリルダウンの URL 反映(ファイルのフォルダ、Phone のタブ)→ ブラウザ戻るボタン自体の全経路対応。
  (スコープB/C として据え置き)

## 参照

- `docs/product/ui-ux-audit.md`(「ScreenShell にパンくず/戻るが無い」)
- `apps/web/app/components/FullSaasScreen.tsx` / `AppShell.tsx` / `lib/nav-history.ts`
