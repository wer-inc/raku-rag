# 0066 — ChatBot evidence and action UI polish (系統 = chatbot / ux)

> Priority: **P2/Medium** / Status: Resolved / Labels: `chatbot`, `ux`, `evidence`

## 背景(なぜ今)

`/chatbot` の回答下に出る citation と quick reply が同じ小さなボタン表現で並び、ユーザーから見て
「根拠を確認する場所」と「回答を別の切り口で見直す操作」の違いが分かりにくかった。

## どんな課題か

- `引用ソース` は実装寄りの表現で、業務ユーザーには「この回答を信頼できる理由」が伝わりにくい。
- `根拠付き回答` と `根拠確認済み` の badge が並び、意味が重複して見える。
- `手順だけ見る` / `判断基準を表にする` / `根拠を確認する` が citation と同じ見た目で、操作の種類が曖昧。

## どこで起きたか

- 画面: `/chatbot`
- API: N/A
- コード: `apps/web/app/components/FullSaasScreen.tsx`, `apps/web/app/globals.css`
- 環境: local / stg
- run id / ingestion id / correlation id: N/A
- 再現条件: citations と quick replies を含む ChatBot 回答を表示する。

## 影響

- 営業デモで「根拠付きで業務利用できる」価値が伝わりにくい。
- 本番クライアントで、回答本文・根拠・追加操作の情報階層が混ざって見える。
- セキュリティやACLへの直接影響はないが、根拠確認の行動を弱く見せることで運用品質の印象が下がる。

## どう解決すべきか

1. 回答 badge は主状態に絞り、`根拠確認済み` / `根拠不足` / `担当者確認` などに整理する。
2. `引用ソース` を `参照した根拠` に置き換え、文書・承認状態・有効日・場所をカード化する。
3. quick reply は `次の見方` として、手順・表・根拠・注意などの用途別 chip にする。
4. keyboard focus と mobile layout を保つ。

## QA checklist

- [ ] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- 回答上部のタグが重複せず、根拠状態が分かる。
- 根拠がカードとして表示され、クリックで既存の根拠詳細を開ける。
- quick reply は citation と区別できる action chip として表示される。
- mobile でもテキスト・badge・操作が重ならない。

## スコープ外

- citation DTO への document title / excerpt 追加。
- backend の structured response schema 化。
- 根拠詳細 viewer の全面再設計。
- server-side RAG / ACL / approval gate の変更。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx`
- `apps/web/app/globals.css`
