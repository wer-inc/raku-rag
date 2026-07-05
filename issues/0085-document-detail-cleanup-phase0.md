# 0085 — ドキュメント詳細ページのP0整理(生JSMONメタデータ編集の撤去 ほか)

> Priority: **P1/High** / Status: Fixed / Labels: `web`, `api`, `security`, `ux`, `stg`

## 背景(調査の結論)

`/documents/:id`(ドキュメント詳細)は ops_owner/tenant_admin 向け画面だが:

- **「メタデータ編集」が生JSMONのテキストエリア**で、初期値が `{"owner":"ops"}` の**ダミー固定**(実際の現在値をロードしない)。そのまま保存で**既存のガバナンスメタデータ(安全カテゴリ・承認状態等)を上書き破壊**しうる footgun。
- **「処理状態」が生JSMONダンプ**(parser/embedding版・checksum・run_id 等の内部情報が露出)。
- **表示バグ**:`利用状態` が常に `pending_review` 固定、`ソース` が placeholder「取り込みソース」固定。
- **API防御の穴**:`GET /admin/documents/{id}/processing-status` に**サーバー側ロールチェックが無い**(テナント分離のみ)。UIで隠しているだけで、field/reader メンバーがトークン直叩きで取得可能。

競合調査の結論:生JSMON編集は業界の table-stakes 以下。承認は /reviews、分類は取込マッピングに正しい入口があり、汎用メタデータエディタの価値は低い。→ **撤去して読める要約に。**

## どう解決したか(フェーズ0)

- **生JSMON「メタデータ編集」+保存を撤去**(上書き事故の元を断つ)。governance編集は /reviews と取込マッピングに集約。
- **処理状態を読める要約に**:文書名 / 利用状態(承認)/ ソース / 分類 / 取り込み状態(日本語)/ チャンク数 / 最終取り込み /(エラー)。内部の生JSMONは **「開発者向け詳細」の `<details>` に折り畳み**。
- **表示バグ修正**:利用状態・ソース・文書名・分類を **document summary の実値**から表示(`citeApproval` / `summary.source_id` など)。ハードコード placeholder を廃止。
- **削除を確認付きに**:「文書を削除」→確認(「取り消せません」)→「削除する/キャンセル」。削除後は「削除しました」表示。
- **API防御(defense-in-depth)**:`documentProcessingStatus` の READ に `assertAnyRoleAllowed(["ops_owner","tenant_admin","platform_admin","admin","owner"])` を追加。**ops_owner を必ず含む**(画面の所有ロールなので外すと自分の画面で403になる)。DELETE は既存 `deleteFromCore`→`assertAdminMutationAllowed` で保護済み。

## どこ

- `apps/web/app/components/FullSaasScreen.tsx`(`DocumentDetailBody` 全面書き換え + `ingestStatusLabel` + 未使用 import 削除)
- `apps/api/src/admin/jobs.controller.ts`(`documentProcessingStatus` にロールガード + `assertAnyRoleAllowed` import)
- tests: `apps/api/test/admin-jobs.e2e-spec.ts`(reader→403)、`tests/contract/test_ingestion_status.py`(ガードmarker)、`tests/contract/test_web_document_detail.py`(FE不変条件)

## QA

- [x] Tier A GREEN(1747)/ 契約テスト GREEN / admin-jobs e2e 13/13(新: reader→403)/ apps/api・web tsc 0 / `next build` 成功 / black clean。
- [ ] stg 反映後、ドキュメント詳細が「読める要約+折り畳みJSON+確認付き削除」になり、利用状態/ソースが実値、を実機確認。

## 参照(この一連の議論)

- 用途・価値・競合の整理(生JSMON編集は撤去、価値は「安全分類・鮮度の後修正」に限定)。
- フェーズ1(安全カテゴリ等の是正を型付きコントロール化)/フェーズ2(取込時AI提案+/reviews確認)は別issueで。
