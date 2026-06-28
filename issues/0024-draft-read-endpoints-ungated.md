# 0024 — ドラフト読取(GET /drafts・/drafts/:id)にロールゲートが無く、テナント内の誰でもレビューキューを閲覧できる(系統 = rbac / read-authz)

> Priority: **P2 / Medium** / Status: **Resolved(BE landed・コミット待ち, 2026-06-28)** / Labels: `rbac`, `authz`, `manufacturing`, `review`, `least-privilege`, `read-authz`
>
> **対応:** `assertReviewViewAllowed`(reviewer + admin級、manifest review-queue `[reviewer,tenant_admin]` 準拠)を
> `roles.ts` に新設し、`GET /drafts`(`:220`)・`GET /drafts/:id`(`:233`)へ適用。ゼロロール/field_user/ops_owner は
> 403。nav 側も ops_owner を review クラスタから除外して整合(0011 DoD#4)。e2e に reviewer 200 / field_user 403 /
> ops_owner 403 を追加 → 112 e2e 緑。create(`:211`)の無ゲートは本 issue 範囲外(B1 #15、別途判断)。

## 背景(なぜ今)

境界監査 B5(認証/RBAC 境界、2026-06-28)で検出。製造業オーバーレイの**集約 read view**(`dashboard`・`safety-telemetry`・`kpi` 等)は `assertReadViewAllowed(req)`(≥1 ロール必須)でゲートされる。ところが**ドラフト読取**(`GET /v1/manufacturing/drafts` 一覧・`GET /drafts/:artifactId` 詳細)は**ロールゲートを一切呼ばず** `requestCore` に直行する。集約ビューが ≥1 ロールを要求するのに、より粒度の細かいドラフト本文の読取が無ゲート、という**内部矛盾**。

これはテナント越境ではない(身元は署名付き principal 由来・RLS/テナント分離は無傷)。**テナント内の職務分掌(least-privilege)漏れ**であり、ゼロロール/`field_user` のテナント成員が API 直叩きで他者のレビューキュー・個別ドラフト(AI 生成本文・生成根拠 provenance・citations・承認決定・reviewer 等)を閲覧できる。

## どんな課題か

- `assertReadViewAllowed` は dashboard 等(`controller.ts:314`)で ≥1 ロールを要求するが、`listDrafts`(`:220-231`)・`draft`(`:233-243`)は**ガード呼び出し無し**。
- 結果、認証済みであれば**ロールに関係なく**レビューキュー全件と個別ドラフト詳細(`content.items`・`source_citations`・`approval_decision`・`reviewer_id` 等)を取得できる。
- manifest はレビューキュー/詳細画面を `rbac=[reviewer, tenant_admin]`(`screens.manifest.json:233,:252`)と宣言しており、UI の表示意図と API の実効認可がズレる(FE で隠しても API が開いている)。
- 期待挙動: ドラフト読取は集約ビューと同等以上の read 認可(最低 `assertReadViewAllowed`、より厳密には reviewer/tenant_admin)を要求する。
- 実際の挙動: 無ゲートで全テナント成員が読める。
- 関連: ミューテーション側の**過剰**制限(reviewer が承認できない)は [0011](0011-rbac-reviewer-cannot-approve.md)、生成(create)の無ゲートは B1 finding #15(同 controller:211)。本 issue は**読取の過小制限**。

## どこで起きたか

- API: `GET /v1/manufacturing/drafts`(list)、`GET /v1/manufacturing/drafts/:artifactId`(detail)。
- コード:
  - 無ゲート: `apps/api/src/manufacturing/manufacturing.controller.ts:220-231`(listDrafts)、`:233-243`(draft)。
  - 対比(ゲート有り): `:314`(dashboard `assertReadViewAllowed`)、`:338`(safety-telemetry 同)。
  - ガード定義: `apps/api/src/auth/roles.ts:19-24`(`assertReadViewAllowed`=≥1 ロール)。
  - 画面宣言: `specs/full-saas/screens.manifest.json:233`(review-queue rbac)、`:252`(review-detail rbac)。
- 環境: 全環境。boundary-audit B5 finding #7。
- run id / correlation id: なし(静的監査)。
- 再現条件:
  1. ゼロロール or `field_user` の認証済みトークンを取得(同一テナント)。
  2. `GET /v1/manufacturing/drafts` を直接叩く。
  3. レビューキュー全件・個別ドラフト本文が 200 で返る。

## 影響

- セキュリティ/職務分掌: 現場ユーザ等が、レビュー前の AI 生成ドラフト(未承認・誤りを含み得る)や承認判断・reviewer 情報を閲覧できる。テナント越境ではないが least-privilege 違反。
- 監査/コンプライアンス: 「誰がレビュー対象を見られるか」の境界が API で担保されず、画面 rbac 宣言と乖離。
- 本番クライアント: 規制系で「レビュー中の文書は承認者のみ閲覧」を要求された場合に満たせない。
- 注意: ミューテーション(承認/却下/割当)は別途 `assertAdminMutationAllowed` で 403 になるため、**書込みは無傷**。本件は読取専用の露出。

## どう解決すべきか

1. **実装方針(BE)**: `listDrafts`(`:220`)・`draft`(`:233`)に read 認可ガードを追加する。最低でも `assertReadViewAllowed`(集約ビューと対称)。職務分掌を厳格化するなら reviewer/tenant_admin 限定の専用ガード([0011](0011-rbac-reviewer-cannot-approve.md) で新設する `REVIEW_APPROVAL_ROLES` の read 版、または `assertReviewViewAllowed`)。どの粒度が正かは spec/manifest(`:233,:252`)に合わせて確定。
2. **防御多層(任意)**: answer-service 内部ルート側でも roles を見て read を制限([0016](0016-document-approval-skip-and-workflow-authz.md) の内部境界ロール再検査と連動)。
3. **テスト方針**: ゼロロール/`field_user` で `GET /drafts`・`/drafts/:id` が 403、reviewer/tenant_admin で 200 になる E2E を `apps/api/test/manufacturing.e2e-spec.ts` に追加。集約ビューの既存挙動を回帰させない。
4. **UI/UX**: FE のナビ/画面 rbac(`reviewer/tenant_admin`)と API 実効認可を一致させる([0011](0011-rbac-reviewer-cannot-approve.md) の nav-rbac↔manifest 整合と連動)。

## QA checklist

- [ ] ゼロロール/field_user で `GET /drafts`・`/drafts/:id` が 403 になる再現テストがある。
- [ ] reviewer/tenant_admin では 200 で従来どおり取得できる(正常系)。
- [ ] 集約 read view(dashboard 等)の認可が回帰していない。
- [ ] tenant/ACL 境界を越えない(本件はテナント内 read 制限で、テナント分離は元から無傷)。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。

## 受け入れ条件(DoD)

- ドラフト読取が集約ビューと整合した read 認可(最低 `assertReadViewAllowed`、または reviewer/tenant_admin)でゲートされる。
- 画面 rbac 宣言(manifest)と API 実効認可が一致する。
- regression test(403/200)が追加されている。
- 既存の ACL・テナント分離・安全ルールを弱めていない。

## スコープ外

- ミューテーション側の RBAC(reviewer が承認できない過剰制限)は [0011](0011-rbac-reviewer-cannot-approve.md)。
- create の無ゲート(B1 #15)・内部境界のロール再検査は [0016](0016-document-approval-skip-and-workflow-authz.md)。
- テナント越境/RLS(本件と無関係、無傷)。

## 参照

- `apps/api/src/manufacturing/manufacturing.controller.ts:220-243`(無ゲート), `:314`/`:338`(対比), `apps/api/src/auth/roles.ts:19-24`
- `specs/full-saas/screens.manifest.json:233`,`:252`
- 由来: 境界監査 B5 finding #7
- 関連: [0011](0011-rbac-reviewer-cannot-approve.md), [0016](0016-document-approval-skip-and-workflow-authz.md)
