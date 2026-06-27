# Sales Demo E2E Use Cases

作成日: 2026-06-27

この文書は、営業用アカウントで AWS sales 環境にログインし、顧客に見せる想定の
ブラウザ操作を漏れなく設計・確認するためのチェックリストです。
`docs/uat/usecase-verification.md` は runtime/UAT テストの証跡であり、この文書は
Next.js frontend と live API をまたぐ sales demo E2E の証跡です。

## ステータス定義

| Status | 意味 |
|---|---|
| VERIFIED-LIVE | Playwright で AWS sales 環境のブラウザ操作と API 到達を確認済み。 |
| VERIFIED-SMOKE | 画面表示・主要 API 読み込み・エラーなしを確認済み。業務操作の完了までは含まない。 |
| DESIGNED-NOT-LIVE | ユースケース設計はあるが、外部資格情報・本番データ・未実装 API が必要なため live 検証対象外。 |
| NOT-DEMO-RUN | 顧客デモ中に実行しない運用として設計しているもの。事前準備または別検証で扱う。 |

## 共通前提

- 対象環境: AWS sales 環境
- 認証: Basic 認証 + Cognito ログイン
- 代表ユーザー: sales demo account
- 代表コレクション: `manuals`
- 失敗条件:
  - `invalid Cognito JWT` が画面または API レスポンスに出る
  - ログイン後のページ遷移・リロードで Basic 認証が再表示される
  - `読み込みに失敗しました` が主要導線に残る
  - 重要 API が 4xx/5xx で失敗し、UI が復旧できない
  - 高リスク・ACL・承認ゲートが緩み、根拠なし回答や権限外引用が出る

## ユースケース一覧

| ID | 領域 | ユースケース | 期待結果 | 主な画面/API | Status |
|---|---|---|---|---|---|
| AUTH-01 | 認証 | 未ログインで workspace URL にアクセスする | `/login` に誘導される | `/login`, Cognito password auth | VERIFIED-LIVE |
| AUTH-02 | 認証 | sales account でログインする | workspace に入り、左サイドバーと右の資料 drawer が表示される | `/api/auth/cognito/password`, `/api/auth-config` | VERIFIED-LIVE |
| AUTH-03 | 認証 | ログイン後にページ遷移・リロードする | Basic 認証の再要求なし。Cognito session が保持される | all workspace routes | VERIFIED-LIVE |
| AUTH-04 | 認証 | 古い JWT または無効 JWT の復旧 | `invalid Cognito JWT` を表示し続けず、再ログイン/再取得へ進める | `getSessionToken`, API client | VERIFIED-LIVE |
| AUTH-05 | 権限 | URL 直打ちで権限外画面を開く | frontend はアクセス不可を表示し、API はサーバ側で拒否する | `AppShell`, RBAC, API auth | VERIFIED-SMOKE |
| SALES-01 | 営業資料 | 右 drawer を開く | `提案資料` が右側から開く | `SalesDemoDrawer` | VERIFIED-LIVE |
| SALES-02 | 営業資料 | サンプルファイルをダウンロードする | MD/CSV の download が開始される | `/sales-samples/*` | VERIFIED-LIVE |
| INGEST-01 | 取込 | 承認済み CSV/Markdown を upload する | `/api/upload` 200、`/v1/ingest` 202/成功、結果に `取込成功` が出る | `/sources/new`, `/api/upload`, `/v1/ingest` | VERIFIED-LIVE |
| INGEST-02 | 取込 | `pending_review` 文書を upload する | 取込後、文書承認キューに承認待ちとして出る | `/sources/new`, `/reviews/documents` | VERIFIED-LIVE |
| INGEST-03 | 取込 | テキスト貼り付けで文書を作る | `.txt` として取込が開始される | `/sources/new`, `/v1/ingest` | VERIFIED-LIVE |
| INGEST-04 | 取込 | ファイル未選択で upload する | API を呼ばず、UI が入力不足を表示する | `/sources/new` | VERIFIED-LIVE |
| INGEST-05 | 取込 | 取込済み文書を一覧で確認する | 最近 upload とテナント文書一覧に反映される | `/documents`, `/v1/manufacturing/documents` | VERIFIED-LIVE |
| INGEST-06 | 取込 | ingestion run を確認する | run ID で状態を参照できる | `/ingestion-runs`, `/v1/manufacturing/ingestion-runs/:runId` | VERIFIED-LIVE |
| CONNECT-01 | 外部ソース | URL/Google Drive/S3/DB 等の接続フォームを選ぶ | ソース種別ごとに必要項目が変わる | `/sources/new` | VERIFIED-SMOKE |
| CONNECT-02 | 外部ソース | 接続設定を保存する | datasource が保存される | `PUT /v1/admin/datasources/:id` | DESIGNED-NOT-LIVE |
| CONNECT-03 | 外部ソース | 保存して同期開始する | sync run が作成され、review_required は pending_review で入る | `/v1/admin/datasources/:id/sync` | NOT-DEMO-RUN |
| CONNECT-04 | 外部ソース | Google Drive OAuth 接続 | refresh token はサーバ側に保持され、client には connection id のみ残る | `/oauth/google/authorize`, callback | DESIGNED-NOT-LIVE |
| QA-01 | 質問 | 通常の保全・品質質問をする | 承認済み根拠がある場合は回答・引用・相関 ID が出る | `/`, `/v1/manufacturing/answer` | VERIFIED-LIVE |
| QA-02 | 質問 | 根拠不足の質問をする | 推測回答をせず `根拠不足` として保留する | `/v1/manufacturing/answer` | VERIFIED-LIVE |
| QA-03 | 質問 | 高リスク質問をする | 安全ゲートが働き、承認済み根拠不足なら回答を止める | `/v1/manufacturing/answer` | VERIFIED-LIVE |
| QA-04 | 質問 | 引用を開く | 引用本文・文書ID・承認状態を確認できる | `/v1/assets/:asset_id`, citation viewer | VERIFIED-LIVE |
| QA-05 | 質問 | 低評価フィードバックを送る | `/v1/feedback` に送信され、改善キューに残る | answer feedback, `/operations/improvements` | VERIFIED-LIVE |
| SEARCH-01 | 検索 | 類似トラブル事例を検索する | 候補・原因・対策が出る。根拠なしなら失敗ではなく候補なしになる | `/sources`, `/v1/manufacturing/trouble-cases/search` | VERIFIED-LIVE |
| SEARCH-02 | 検索 | source sync status を見る | source_id 単位の同期状態を参照できる | `/sources`, `/v1/manufacturing/sources/:sourceId/sync-status` | VERIFIED-LIVE |
| SEARCH-03 | 検索 | retrieval debug を実行する | 検索候補、採用/除外理由、安全ゲート理由が出る | `/admin/retrieval/debug`, `/v1/search`, `/v1/manufacturing/answer` | VERIFIED-LIVE |
| APPROVAL-01 | 文書承認 | pending_review 文書を承認する | `approved` に変わり、正式な根拠候補になる | `/reviews/documents`, `/v1/manufacturing/documents/:id/approval` | VERIFIED-LIVE |
| APPROVAL-02 | 文書承認 | 文書を旧版化する | `obsolete` に変わり、高リスク回答の正式根拠にならない | `/reviews/documents` | VERIFIED-LIVE |
| APPROVAL-03 | 承認ルール | ガバナンス状態を見る | AI 出力 draft-only、高リスク承認済み引用必須が表示される | `/reviews/settings`, `/v1/manufacturing/governance/status` | VERIFIED-SMOKE |
| DRAFT-01 | AIドラフト | AI ドラフトを作成する | draft 状態で作成され、自動承認されない | `/reviews`, `/v1/manufacturing/drafts` | VERIFIED-LIVE |
| DRAFT-02 | AIドラフト | reviewer を割り当てる | reviewer_id が反映される | `/reviews/:artifactId/assign` | VERIFIED-LIVE |
| DRAFT-03 | AIドラフト | AI ドラフトを承認/却下する | human decision により terminal 状態になる | `/reviews/:artifactId/review` | VERIFIED-LIVE |
| OPS-01 | 運用 | ホーム/運用 dashboard を開く | KPI、安全テレメトリ、ガバナンスが表示される | `/home`, `/operations` | VERIFIED-SMOKE |
| OPS-02 | 運用 | 安全テレメトリを見る | 高リスク・安全ブロック内訳が出る | `/operations/safety` | VERIFIED-SMOKE |
| OPS-03 | 運用 | 品質 KPI を見る | 自己解決率、根拠あり回答率、根拠不足率が出る | `/operations/quality` | VERIFIED-SMOKE |
| OPS-04 | 運用 | 導入効果レポートを見る | 影響指標と安全/品質サマリーが出る | `/operations/impact-report` | VERIFIED-SMOKE |
| OPS-05 | 改善 | 改善キューを見る | feedback 由来と監査由来の改善候補が表示される | `/operations/improvements`, `/v1/manufacturing/improvements` | VERIFIED-LIVE |
| AUDIT-01 | 監査 | 監査ログを見る | audit events が表示され、重要操作が追跡できる | `/audit`, `/v1/manufacturing/audit/events` | VERIFIED-SMOKE |
| AUDIT-02 | 監査 | コンプライアンス出力を見る | audit export と data-use policy を確認できる | `/compliance/export` | VERIFIED-SMOKE |
| ADMIN-01 | 管理 | ACL/ロール画面を見る | ACL deny-by-default と grant が見える | `/admin/access`, `/v1/admin/acl` | VERIFIED-SMOKE |
| ADMIN-02 | 管理 | ACL simulator を実行する | ユーザー別に引用有無が変わり、権限外は漏れない | `/admin/access`, `/api/dev-token`, answer API | VERIFIED-LIVE |
| ADMIN-03 | 管理 | No-train/provider policy を見る | no-train default、リージョン、provider policy が見える | `/admin/provider-policy` | VERIFIED-SMOKE |
| ADMIN-04 | 管理 | retrieval/logging/privacy 設定を見る | 現行設定が JSON/表で確認できる | `/admin/retrieval`, `/admin/logging-privacy` | VERIFIED-SMOKE |
| ADMIN-05 | 管理 | users/integrations/API/billing/support を開く | 画面 smoke は可能。未実装 API は mock/spec 表示として扱う | `/admin/*` | DESIGNED-NOT-LIVE |
| NEG-01 | 異常系 | API 停止/ネットワーク失敗 | 画面は復旧可能なエラーを表示する | `ScreenLoadError` | DESIGNED-NOT-LIVE |
| NEG-02 | 異常系 | 未承認/旧版のみの高リスク根拠 | 回答しない、または参考扱いで warning を出す | answer safety gate | VERIFIED-LIVE |
| NEG-03 | 異常系 | 不正な metadata JSON を保存する | validation error を表示し、壊れた状態にしない | document detail metadata | DESIGNED-NOT-LIVE |

## デモで必ず通すシナリオ

1. Login: Basic + Cognito で `/home` へ入る。
2. Sales resources: 右 drawer から sample CSV/MD を download する。
3. Ingestion: `/sources/new` で approved 文書と pending_review 文書を upload する。
4. Document list: `/documents` で upload 済み文書を確認する。
5. Approval: `/reviews/documents` で pending_review 文書を承認する。
6. Question: `/` で通常質問・根拠不足・高リスク質問を確認する。
7. Feedback: 回答に `要改善` を付け、`/operations/improvements` に出ることを確認する。
8. Draft review: `/reviews` で AI ドラフトを作り、assign/review する。
9. Operations: `/operations`, `/operations/safety`, `/operations/quality`, `/audit` を確認する。
10. Security: `/admin/access` の ACL simulator と `/admin/retrieval/debug` を確認する。

## 外部コネクタの扱い

顧客デモ中に新規の外部 connector sync は実行しません。理由は以下です。

- 外部サービスの資格情報・OAuth 同意・IP 許可・テナントデータが必要になる。
- 顧客環境の secret をブラウザや画面共有に出さない必要がある。
- connector sync は事前準備・個別検証で完了させ、デモ中は取り込まれた結果と同期状態を説明する。

そのため、live demo では connector UI、保存ポリシー、sync status、ingestion run の確認までを扱い、
本物の Box/Google Drive/Notion/kintone/S3/DB 連携は顧客環境ごとの導入タスクとして扱う。

## Playwright 検証結果

実行日: 2026-06-27

対象:

- URL: `http://rakura-awsne-r4xgwhvpgcec-1715490950.ap-northeast-1.elb.amazonaws.com`
- 認証: Playwright `httpCredentials` で Basic 認証を通し、Cognito password login で sales account にログイン
- sales Cognito claims: tenant `demo`, groups/roles `sales_demo`, `reviewer`, `tenant_admin`

### 実行結果サマリー

| Area | Result | Evidence |
|---|---|---|
| Auth | PASS | `/login` から `/home` へ遷移。sales drawer tab 表示。`/sources/list` refresh 後も `invalid Cognito JWT` / load failure なし。 |
| Sales resources | PASS | 右 drawer を開き、`approved-work-instruction.md` の download を確認。 |
| Upload / ingest | PASS | approved file, pending_review file, text paste の 3 種を upload。`/api/upload` と `/v1/ingest` が成功し、admin ingestion run は `parse/chunk/embed/index=succeeded`。 |
| Validation | PASS | file 未選択 submit で `ファイルを選択してください` を表示し、壊れた状態にならない。 |
| Documents | PASS | `/documents` で直近 upload 控えを確認。 |
| Approval | PASS | pending_review 文書を `approved` に変更。別の一時文書を `obsolete` に変更。 |
| Question | PASS | `PW-E2E-20260627` で `回答済み`、引用 3 件、引用ビューア表示を確認。 |
| Safety gate | PASS | 点検周期/締付トルク/安全カバーなどの作業手順寄り質問は `根拠不足` または安全保留になり、危険な断定をしない。 |
| Feedback / improvement | PASS | `要改善` feedback を送信し、`/operations/improvements` に表示。 |
| Trouble search / sync status | PASS | `/sources` の事例検索と source status form を実行し、auth/load error なし。 |
| Draft review | PASS | `/reviews` で AI draft 作成、reviewer assign、human approval を確認。 |
| Ops / audit / policy | PASS | `/home`, `/operations`, `/operations/safety`, `/operations/quality`, `/operations/impact-report`, `/reviews/settings`, `/audit`, `/compliance/export`, `/admin/provider-policy`, `/admin/retrieval`, `/admin/logging-privacy`, `/sources/list` の 12 route smoke 成功。 |
| Retrieval debug | PASS | `/admin/retrieval/debug` で診断実行。検索候補・判定・パイプライン表示を確認。 |
| ACL | PASS | `/admin/access` 表示、権限シミュレーター操作を確認。 |

### 修正した検証ブロッカー

初回検証では、upload run は成功していたにもかかわらず sales account の `/v1/search`
が空になり、通常質問が引用なしの `根拠不足` になった。

原因:

- Cognito sales user は `sales_demo` role/group を持つ。
- 既存 demo ACL は `alice`, `misaki`, `bob`, `carol`, `dave` の user grant のみ。
- ACL は deny-by-default のため、sales account には `manuals` collection の read grant がなく、検索候補が全て除外されていた。

対応:

- live sales 環境に `role:sales_demo -> collection:manuals read` を追加。
- `scripts/demo/demo_seed.py` に同じ role grant を追加し、次回 seed でも再発しないようにした。

追加後:

- `/v1/search` は `pw-e2e-text-*` を含む候補を返す。
- `PW-E2E-20260627` は frontend で `回答済み`、引用 3 件、引用ビューア表示まで確認済み。
- 作業手順・締付トルクなど高リスク寄りの言い方は、引き続き安全ゲートで保留される。

### 画面証跡

Playwright screenshots:

- `/tmp/raku-usecase-home-after-login.png`
- `/tmp/raku-usecase-sales-drawer.png`
- `/tmp/raku-usecase-upload-approved.png`
- `/tmp/raku-usecase-documents-list.png`
- `/tmp/raku-usecase-approval-approved.png`
- `/tmp/raku-usecase-improvements.png`
- `/tmp/raku-usecase-draft-approved.png`
- `/tmp/raku-usecase-ops-smoke-final.png`
- `/tmp/raku-usecase-retrieval-debug-after-acl.png`
- `/tmp/raku-usecase-acl-after-acl.png`
- `/tmp/raku-usecase-citation-final.png`

### デモ時の注意

- 通常の引用付き回答デモは、まず `PW-E2E-20260627` のような検索・要約型の質問で見せる。
- `点検周期`, `締付トルク`, `安全カバーを外す` など作業判断に近い質問は、安全ゲートのデモとして扱う。
- 外部 connector sync は本番資格情報が必要なため、顧客デモ中には実行しない。事前同期済みデータ、source status、ingestion run で説明する。
