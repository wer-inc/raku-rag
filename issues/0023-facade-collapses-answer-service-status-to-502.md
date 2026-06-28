# 0023 — NestJS facade が answer-service の意味付き 4xx を一律 502 に潰し理由も失う(系統 = boundary / error-propagation)

> Priority: **P1 / High** / Status: **Resolved(BE landed・コミット待ち, 2026-06-28)** / Labels: `boundary`, `error-handling`, `manufacturing`, `review`, `ux`, `api-contract`
>
> **対応:** `requestCore` で upstream の**ドメイン 4xx(403/404/409/422)のみ**を同ステータス+理由で透過し、
> 内部境界フォルト(401 internal-auth / 400 missing-header)と upstream 5xx は**汎用 502**へ丸めて upstream の
> 生ボディを転送しない(CWE-209 情報開示を回避)。敵対的レビューで「5xx 生例外文字列漏えい」を検出→是正済み。
> e2e に 409 透過 / 422 透過 / 5xx→502(機微非漏えい)を追加 → 112 e2e 緑。FE 側の 403/409 出し分け表示は 0015。

## 背景(なぜ今)

境界監査 B1(承認/ドラフト契約、2026-06-28)で検出。answer-service は承認/レビュー/割当の失敗を**意味付きステータス**で返すよう実装されている — `InvalidTransitionError→409`(状態競合)、`PermissionError→403`(認可)、`ValueError→422`(入力不正)。コードコメントも「Surface 409 so the facade returns a real 4xx, not 502.」と明示する(`server.py:2521`)。
ところが NestJS facade の共通プロキシ `requestCore` が、**non-2xx をすべて `BadGatewayException`(502)へ潰し**、元のステータスもボディの理由文も破棄する(`manufacturing.controller.ts:94-96`)。answer-service が苦心して付けた 409/403/422 が facade で消える。

## どんな課題か

- レビュアーが draft 状態のドラフトを承認しようとすると、backend は本来 `409 InvalidTransition`(「先に担当割当が必要」)を返すが、FE には `502 answer-service error: 409` として届き、**「先に割り当ててください」と誘導できない**。
- 認可不足(`403`)・入力不正(`422`)も同様に 502 に化け、FE は 403/409/422 を区別できず汎用エラー表示になる(`api-client.ts:41-43` は `body.message` か `HTTP ${status}` のみ)。
- 期待挙動: facade は upstream の 4xx(少なくとも 403/409/422)を**ステータスと理由を保ったまま透過**し、FE が状態競合・認可・入力不正を出し分けられる。
- 実際の挙動: 全失敗が 502 BadGateway + `answer-service error: <status>` の文字列に潰れる。
- 関連副次: この潰しは review/assign だけでなく `requestCore` を通る**全 manufacturing ルート共通**(answer/approval/document 等)に及ぶ。

## どこで起きたか

- 画面: `/reviews/:id`(レビュー詳細の承認/却下)、`/reviews/documents`(文書承認)— エラー駆動の回復導線が出せない。
- API: `requestCore`(全 manufacturing プロキシ)。
- コード:
  - answer-service(正): `apps/answer-service/server.py:2519-2527`(`InvalidTransitionError→409` / `PermissionError→403` / `ValueError→422`、コメント `:2520-2521`)。
  - facade(潰す): `apps/api/src/manufacturing/manufacturing.controller.ts:94-96`(`if (!upstream.ok) throw new BadGatewayException(...)`)。
  - FE(受け側): `apps/web/lib/api-client.ts:39-46`(`jsonOrThrow`)、`apps/web/app/components/FullSaasScreen.tsx:2027-2029`(onReview の汎用エラー表示)。
- 環境: 全環境(local / AWS stg)。boundary-audit B1 finding #4。
- run id / correlation id: なし(静的監査)。
- 再現条件:
  1. ドラフトを生成(status=draft)。
  2. 担当割当をせず `/reviews/:id` で「承認・公開」を押す。
  3. answer-service は 409 を返すが、FE には 502 として届く。

## 影響

- 営業デモ/本番: レビュアーが「なぜ失敗したか」分からず操作不能のフリクション。安全クリティカルな承認操作のエラー回復(先に割当・権限申請・入力修正)が成立しない。
- **0015(レビュー詳細 UX)の前提**: 「draft では先に担当割当」のインライン誘導や、403/409/422 の出し分けは、この 502 潰しが直らないと**実装しても機能しない**。
- 監査/安全: 安全ルール・ACL 自体は無傷(認可の最終判定は backend 側で正しく 403 を出している)。問題はその理由が UI に届かない伝播欠落のみ。

## どう解決すべきか

1. **実装方針(facade)**: `requestCore` で upstream が non-2xx のとき、ステータス(少なくとも 403/409/422、できれば 4xx 全般)とボディの `error` をそのまま `HttpException` へマップして透過する(`new HttpException(body, upstream.status)` 等)。5xx は従来どおり 502/500 に丸めてよい。接続不能(`.catch`)は `BadGatewayException` のまま。
2. **UI/UX 方針(FE)**: `api-client` のエラーをステータス付きで受け取れるようにし(`status` を保持するエラー型)、FullSaasScreen が 409=状態競合(「先に担当を割り当ててください」)、403=権限不足、422=入力不正、を文言で出し分ける。0015 と連動。
3. **テスト方針**: facade のユニット/契約テストで upstream 409/403/422 が同ステータスで透過されること、E2E(`apps/api/test/manufacturing.e2e-spec.ts`)で draft→approve が 409 として返ること、Playwright で「先に割当」誘導が出ることを確認。
4. **移行/運用上の注意**: 502→4xx 化でアラート/監視のしきい値が変わる(503/502 を異常とする監視は 4xx を正常系に再分類)。observability の redaction で `error` 文に PII が混じらないことを確認。

## QA checklist

- [ ] facade が upstream 403/409/422 を同ステータスで透過する再現テストがある。
- [ ] draft→approve が FE で「先に割当」誘導付きの状態競合として表示される(正常系)。
- [ ] 認可不足(reviewer 権限なし等)が 403 として区別表示される(失敗時表示)。
- [ ] tenant/ACL 境界を越えない(エラーボディに他テナント情報が漏れない)。
- [ ] security/safety gate を弱めていない(認可判定は backend のまま、facade は伝播のみ変更)。
- [ ] Playwright または API smoke で 4xx 透過を確認できる。

## 受け入れ条件(DoD)

- answer-service の 403/409/422 が FE まで意味を保って届き、レビュー UI が状態競合・認可・入力不正を出し分けられる。
- regression test(facade 透過 + E2E)が追加されている。
- 接続不能(answer-service unreachable)は引き続き 502 として扱う。
- 既存の認可・安全・監査ルールを弱めていない(伝播のみの変更)。

## スコープ外

- レビュー UX 全般(確認ダイアログ/二重送信/活性条件)は [0015](0015-review-detail-ux-state-machine-mismatch.md)。
- RBAC ガード自体(reviewer が承認できない)は [0011](0011-rbac-reviewer-cannot-approve.md)。
- answer-service 側のステータスマッピング(既に正しい)の変更。

## 参照

- `apps/answer-service/server.py:2519-2527`(正しいマッピング+意図コメント)
- `apps/api/src/manufacturing/manufacturing.controller.ts:94-96`(502 潰し)
- `apps/web/lib/api-client.ts:39-46`, `apps/web/app/components/FullSaasScreen.tsx:2027-2029`
- 由来: 境界監査 B1 finding #4(承認/ドラフト契約)
- 関連: [0015](0015-review-detail-ux-state-machine-mismatch.md)(レビュー UX)、[0011](0011-rbac-reviewer-cannot-approve.md)(RBAC)
