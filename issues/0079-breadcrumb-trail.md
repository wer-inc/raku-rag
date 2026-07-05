# 0079 — 画面上部にパンくず(祖先へ直接ジャンプ)を追加(系統 = web / navigation / UX)

> Priority: **P2/Medium** / Status: Fixed / Labels: `web`, `ux`, `navigation`, `a11y`, `stg`

## 背景

0078 で全画面に「← 戻る」(直前へ戻る)を入れた。続くスコープBとして、**祖先(親一覧)へ 1 クリックで
直接ジャンプ**できるパンくずを追加し、「メニューから再入」をさらに不要にする。

## どう解決したか

- `ScreenShell`(全非ルート画面)に「← 戻る」ピルと並べてパンくずを表示。
  - 祖先 = **ホーム**(全画面の root)+ 詳細/孤立画面は**親一覧**(`SCREEN_PARENT_HREF` の親、
    ラベルは `navLabelFor()`)。末尾に現在画面を `aria-current="page"` で表示。
  - 例: `ホーム / ファイル / 文書詳細`(ファイルはクリックで一覧へ)、`ホーム / ファイル`(トップ画面)。
  - 祖先は `next/link` の Link(=クライアント遷移)。現在画面は非リンク。
- `lib/full-saas.ts` に `navLabelFor(href)`(NAV_GROUPS + HOME_NAV から href→ラベル)を追加。
- CSS: `.topbar-nav`(戻る+パンくず行)/`.topbar-breadcrumb`(区切り `/`、hover 下線、
  `:focus-visible` アウトライン、`aria-current` 強調)。

## どこ

- `apps/web/lib/full-saas.ts`(`navLabelFor`)
- `apps/web/app/components/FullSaasScreen.tsx`(`breadcrumbAncestors` + `ScreenShell`)
- `apps/web/app/globals.css`(`.topbar-nav` / `.topbar-breadcrumb`)
- `tests/contract/test_web_back_navigation.py`(breadcrumb マーカー追加)

## QA checklist

- [x] typecheck + `next build` 成功。
- [x] Tier A gate GREEN、契約テスト(6 cases / 20 subtests)。
- [x] a11y: `nav[aria-label]` + `aria-current="page"` + focus-visible。
- [x] tenant/ACL / security を弱めていない(表示のみ)。
- [ ] stg 反映後に実機でパンくず遷移を確認。

## 受け入れ条件(DoD)

- 全非ルート画面にパンくず(ホーム + 親一覧 + 現在)が出る。
- 祖先クリックでその画面へ遷移できる。
- 直前戻る(← 戻る, 0078)と併存し、詳細画面から親一覧へ直接ジャンプできる。

## スコープ外(スコープC、据え置き)

- 状態ドリルダウンの URL 反映(ファイルのフォルダ、Phone のタブ/詳細)→ ブラウザ戻るボタン自体を
  全経路で機能させる。

## 参照

- `issues/0078-universal-back-navigation.md`
- `docs/product/ui-ux-audit.md`(「ScreenShell にパンくず/戻るが無い」)
