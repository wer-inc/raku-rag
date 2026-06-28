# 0011 — `reviewer`/`ops_owner` ロールが承認できない RBAC 矛盾(系統 ①②)

> Priority: **P0 / High** / Status: Open / Labels: `rbac`, `manufacturing`, `review`, `approval`, `least-privilege`

## 背景(なぜ今)

製品は専用ロール「承認者(`reviewer`)」を持ち、ワークスペース既定ユーザーも「品質保証部 · 承認者」
(`apps/web/lib/full-saas.ts:28`)。設計でも **draft の承認は reviewer のアクション**
(`specs/002-.../contracts/mfg-interfaces.md:141`「approved は reviewer のみ」/ `mfg-openapi.md:162`)、
manifest の review 画面 rbac は `['reviewer','tenant_admin']`。つまり「承認者ロール=承認できる人」が前提。

## 現状(根拠)

- `apps/api/src/auth/roles.ts:4` — `ADMIN_MUTATION_ROLES = {admin, tenant_admin, platform_admin, owner}`。
  **`reviewer` も `ops_owner` も含まれない。**
- `assertAdminMutationAllowed`(`roles.ts:6-11`)が以下に掛かる:
  - `@Post("documents/:documentId/approval")` — `manufacturing.controller.ts:193`(文書 承認/旧版化)
  - `@Post("drafts/:artifactId/assign")` — `:252`(レビュー担当割当)
  - `@Post("drafts/:artifactId/review")` — `:268`(ドラフト 承認/却下)
- よって純粋 `reviewer`(`apps/web/app/api/dev-token/route.ts:37` `carol:["reviewer"]`)や
  `ops_owner`(`dave`)は、UI で「承認」ボタンを押せても API が **403 Forbidden**。
- dev-token issuer のコメントが既知の回避策を明言:「デモ reviewer に tenant_admin を付与して
  レビューループ(assign/approve, 文書承認)を使えるようにする」(`route.ts:32`、`:35` `alice:["tenant_admin","reviewer"]`、
  `:39` `misaki`、`:40` `sales-demo`)。alice/misaki/sales-demo が tenant_admin 兼務なので**デモでは露見しない**。
- nav-rbac は reviewer に `/reviews/*` を開放(`apps/web/lib/nav-rbac.ts:23-28, 86-87`)が、manifest は
  承認ルール画面を `tenant_admin` 限定(`screens.manifest.json:285`)= ルートゲートと manifest の齟齬。

## ギャップ

専用 `reviewer` ロールが**中核アクション(承認)に対して機能しない**。職務分掌(承認者 ≠ テナント管理者)が
崩れ、「全承認者に tenant_admin を付与」する運用=最小権限違反。本番(Cognito)では `reviewer` claim を
持つ実ユーザーが 403 を踏む。

## 提案作業(何をどう対応)

1. **reviewer 級ガードを新設**(`apps/api/src/auth/roles.ts`):
   ```ts
   const REVIEW_APPROVAL_ROLES = new Set(["reviewer", "ops_owner", ...ADMIN_MUTATION_ROLES]);
   export function assertReviewApprovalAllowed(req: Request): void {
     const roles = req.principal?.roles ?? [];
     if (!roles.some((r) => REVIEW_APPROVAL_ROLES.has(r))) {
       throw new ForbiddenException("reviewer or admin role required");
     }
   }
   ```
   ※ `ops_owner` を含めるかは設計確認(`mfg-interfaces.md:141` は reviewer のみ言及)。
2. **承認系ルートのガードを差し替え**(`manufacturing.controller.ts`):
   `assertAdminMutationAllowed` → `assertReviewApprovalAllowed` を `:193`(approval)・`:252`(assign)・
   `:268`(review)に適用。**`documents/:id/metadata`(`:177`)・`policy/data-use` PUT(`:374`)は本来の
   管理操作なので admin-only のまま残す**(取り違えない)。
3. **回避用 grant を撤去**(`route.ts:35-40`):`carol` を pure reviewer のまま、alice/misaki から
   `tenant_admin` を外しても承認ループが回ることを確認。コメント `:32` を更新。
4. **nav-rbac ↔ manifest の齟齬解消**:承認ルール画面(→[0014](0014-approval-rules-settings-non-functional.md))を
   tenant_admin 限定にするなら `REVIEWER_HREFS` から `/reviews/settings` を外す(`nav-rbac.ts:23-28`)、
   逆に reviewer 可とするなら manifest を直す。どちらが正かを spec で確定。
5. (任意・防御多層)職務分掌の最終ガードは [0016](0016-document-approval-skip-and-workflow-authz.md) と連動。

## 受け入れ条件(DoD)

- [ ] `carol`(roles=`["reviewer"]`)で割当・承認・却下・文書承認・旧版化が 200 で通る。
- [ ] `tenant_admin` を一切持たない reviewer の E2E(`apps/api/test/manufacturing.e2e-spec.ts` に追加)が緑。
- [ ] 管理専用操作(metadata 更新・data-use PUT)は reviewer-only で従来どおり 403。
- [ ] `nav-rbac.ts` と `screens.manifest.json` の rbac が一致。

## スコープ外

- 本番 IdP(Cognito)側ロールマッピング設計そのもの(別途)。UI ボタンの出し分けは [0015](0015-review-detail-ux-state-machine-mismatch.md)。

## 参照

- `apps/api/src/auth/roles.ts:4-11`, `apps/api/src/manufacturing/manufacturing.controller.ts:177/193/252/268/374`
- `apps/web/app/api/dev-token/route.ts:32-41`, `apps/web/lib/nav-rbac.ts:23-28/48-52/86-87`, `apps/web/lib/full-saas.ts:28`
- `specs/002-manufacturing-field-knowledge-rag/contracts/mfg-interfaces.md:141`, `.../mfg-openapi.md:162`, `specs/full-saas/screens.manifest.json:285`
