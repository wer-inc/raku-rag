# 0070 — 根拠文書レビューでデータ1件ごとの確認とソース単位承認の判断材料が不足(系統 = product / ux / approval)

> Priority: **P1 / High** / Status: Open / Labels: `product`, `ux`, `approval`, `datasource`, `document-review`

## 背景(なぜ今)

データ同期後のレビュー導線を確認する中で、根拠文書レビュー画面は `pending_review` 文書を承認/旧版化
できるが、レビュー担当者が「何を見て承認すべきか」を画面内で判断しづらいことが分かった。

ユーザー要望として、全データを必ず1件ずつ承認するより、データソース単位でまとめて承認できる導線は
必要。ただし、source丸ごと承認する前に、個別データ・サンプル・差分・例外を確認できる必要がある。

## どんな課題か

- 現状の `/reviews/documents` は文書ID、collection、発効日、chunk数、承認状態、承認/旧版化操作が中心。
- 文書または同期データ1件ごとの本文プレビュー、抽出メタデータ、risk tags、mapping結果、同期元、差分、
  ingestion run との関係が見えにくい。
- source単位の承認操作が無いため、多数件同期ではレビュー負荷が高い。
- 逆に、source単位承認だけを追加すると、中身を見ずに正式根拠化できてしまい、安全・監査上危険。

期待挙動:

- reviewer は、source単位のレビュー画面で「件数、承認待ち、エラー、サンプル、risk分類、変更差分」を見て
  まとめて承認できる。
- 同時に、必要なときは文書/レコード1件の詳細へドリルダウンし、本文プレビュー・抽出メタデータ・引用候補を
  確認できる。
- high-risk / unknown mapping / validation warning / large diff などは一括承認から除外、または明示確認を要求する。

実際の挙動:

- 画面上は各行の識別子と状態しか判断材料が薄く、1件ごとの中身確認もsource単位の安全な承認も弱い。

## どこで起きたか

- 画面: `/reviews/documents` の根拠文書レビュー
- 画面: `/sources/list` / `/sources/new` からの同期後導線
- API: `GET /v1/manufacturing/documents`
- API: `POST /v1/manufacturing/documents/:documentId/approval`
- コード: `apps/web/app/components/FullSaasScreen.tsx` (`DocumentApprovalQueueBody`)
- コード: `apps/answer-service/server.py` (`/internal/manufacturing/documents`, datasource sync)
- 環境: local UI/code review
- run id / ingestion id / correlation id: なし
- 再現条件:
  1. `review_required` datasource から複数文書/レコードを同期する。
  2. `/reviews/documents` を開く。
  3. reviewer が各行の中身やsource単位の品質を画面内で確認して承認判断できるかを見る。

## 影響

- 営業デモへの影響: 「レビューして正式根拠化する」価値は伝わるが、実務でどう確認するかが弱く見える。
- 本番クライアントへの影響: 多数件同期時にレビューが滞留するか、逆に中身を見ない承認が運用化する。
- セキュリティ/安全: high-risk 文書やmapping異常をまとめて正式根拠化すると、approved citation gate の前提が弱くなる。
- データ品質: 誤分類、古い文書、欠落メタデータ、抽出失敗が承認前に見つけづらい。
- UX: reviewer が文書IDだけを見て判断する状態になり、承認作業の信頼感が低い。

## どう解決すべきか

1. 実装方針:
   - `source_id` / `ingestion_run_id` / `approval_status` で文書をグルーピングできる review projection を追加する。
   - source単位の bulk approval API を追加する場合は、対象条件・除外条件・件数・actor・reason を監査する。
   - high-risk、validation warning、unknown mapping、parse failed、obsolete candidate、review_overdue は
     bulk approval の既定対象から外す。
2. UI/UX 方針:
   - `/reviews/documents` を「source別キュー + 文書詳細ドリルダウン」にする。
   - source行には、総件数、承認待ち、正式根拠、要確認、同期日時、policy、代表サンプルを表示する。
   - source詳細では、検索/フィルタ、サンプルプレビュー、差分、validation warning、個別承認を出す。
   - bulk action は `このsourceの警告なしN件を承認` のように対象を明示し、確認ダイアログで reason を必須にする。
3. テスト方針:
   - 多数件 datasource sync の表示、source group、個別詳細、bulk対象除外を unit/Playwright で固定する。
   - bulk approval が tenant境界を越えないこと、warning/high-risk を既定除外することを API test で確認する。
   - audit event に source_id、対象件数、除外件数、reason、actor が残ることを確認する。
4. 移行や運用上の注意:
   - 既存の個別承認 API は残し、bulk approval は安全な上位操作として追加する。
   - trusted datasource policy とは別概念にする。`trusted` は今後の同期をsource-of-truth扱いする設定、
     bulk approval は今回同期された pending_review の正式化操作。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- reviewer が source単位で承認待ちの内訳と代表サンプルを確認できる。
- reviewer が文書/レコード1件の本文プレビュー、抽出メタデータ、警告、同期元を確認できる。
- warning/high-risk/parse failure/unknown mapping は bulk approval の既定対象から外れる。
- source単位 bulk approval は actor/reason/target count/excluded count を監査する。
- 個別承認、source単位承認ともに既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- trusted datasource policy の自動拡大。
- 中身を確認できないまま全件 approved にする bypass。
- full DMS / e-signature / 多段承認。
- AIドラフトレビューの状態機械変更。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx` (`DocumentApprovalQueueBody`)
- `packages/shared/src/dto/manufacturing.ts`
- `apps/api/src/manufacturing/manufacturing.controller.ts`
- `apps/answer-service/server.py`
- [0022-approval-flow-information-architecture.md](0022-approval-flow-information-architecture.md)
- [0039-document-library-operational-ux.md](0039-document-library-operational-ux.md)
- [0069-public-ingest-approved-metadata-bypass.md](0069-public-ingest-approved-metadata-bypass.md)
