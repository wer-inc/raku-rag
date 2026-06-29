# Client Tenant E2E Verification

実行日: 2026-06-27

この文書は、sales demo account ではなく、実クライアント導入を想定した tenant / role
分離の live E2E 検証結果です。

## 対象環境

- AWS sales environment:
  `http://rakura-awsne-r4xgwhvpgcec-1715490950.ap-northeast-1.elb.amazonaws.com`
- 認証:
  - HTTP Basic auth
  - Cognito password login
- Tenant: `client-uat`
- Collection: `manuals`
- Credential storage: AWS Secrets Manager `raku-rag-sales/client-uat-users`

## 作成したクライアント想定ユーザー

| User | Tenant | Cognito group/role | 用途 |
|---|---|---|---|
| `client-admin-uat@example.com` | `client-uat` | `tenant_admin` | 初期設定、ACL、データ取込 |
| `client-reviewer-uat@example.com` | `client-uat` | `reviewer` | 文書承認 |
| `client-user-uat@example.com` | `client-uat` | `field_user` | 質問・引用確認 |

パスワードは文書化しない。Secrets Manager の secret を使う。

## 実施した設定

`client-uat` tenant に対し、ACL deny-by-default を保ったまま次の role-based read grant を設定した。

| Scope | Subject type | Subject | Permission |
|---|---|---|---|
| collection `manuals` | role | `tenant_admin` | read |
| collection `manuals` | role | `reviewer` | read |
| collection `manuals` | role | `field_user` | read |

## Playwright 検証結果

| ID | Result | 内容 | Evidence |
|---|---|---|---|
| CLIENT-AUTH-ADMIN | PASS | client admin で Cognito login。tenant は `client-uat`、role は `tenant_admin`。sales drawer は表示されない。 | live browser |
| CLIENT-ACL-ROLE-GRANTS | PASS | client admin が role-based collection read ACL を設定。 | `PUT /v1/admin/acl` 200 |
| CLIENT-INGEST-ADMIN-UPLOAD | PASS | client admin が approved 文書と pending_review 文書を通常 upload 画面から投入。 | `client-uat-approved-mqvn58xk`, `client-uat-pending-mqvn58xk` |
| CLIENT-REVIEWER-APPROVAL | PASS | client reviewer が pending_review 文書を承認。 | `/reviews/documents` |
| CLIENT-FIELD-ANSWER-CITATION | PASS | client field user が `CL-UAT-20260627` を質問し、`回答済み`、引用 2 件、引用ビューア表示を確認。 | `/`, citation viewer |
| CLIENT-FIELD-RBAC-DIRECT-URL | PASS | field user が `/admin/access` に直アクセスしても、権限なし画面を表示。 | `AppShell` RBAC |
| CLIENT-TENANT-ISOLATION-SEARCH | PASS | field user が自 tenant 文書を検索可能。demo tenant の `pw-e2e` 文書は検索結果に出ない。 | `POST /v1/search` |
| CLIENT-FIELD-REFRESH | PASS | field user で refresh 後も Basic 再要求・`invalid Cognito JWT`・load failure なし。 | browser refresh |
| CLIENT-TENANT-ISOLATION-SALES | PASS | sales demo tenant から `CL-UAT-20260627` を検索しても client tenant 文書は出ない。 | `POST /v1/search` |

Summary:

```text
passed=9
failed=0
badApi=[]
```

Screenshots:

- `/tmp/raku-client-uat-admin-upload.png`
- `/tmp/raku-client-uat-reviewer-approval.png`
- `/tmp/raku-client-uat-field-user-citation.png`

## 判定

実クライアント導入を想定した最小の本番導線は PASS。

- Cognito の tenant claim / group claim から principal を確定している。
- tenant ごとに ACL が分離されている。
- 管理者、承認者、一般ユーザーの責務が分かれている。
- 一般ユーザーは管理画面に直接アクセスできない。
- 取込、承認、質問、引用確認が同一 client tenant 内で成立する。
- demo tenant と client tenant の検索結果は混ざらない。

## 残課題

- 実クライアントの本物の IdP / SSO 連携は未検証。
- 実データ量、実ファイル形式、外部 connector sync は顧客環境の資格情報で別途 UAT が必要。
- 請求、SLA、監査ログの長期保存、インシデント運用は運用受入テストで扱う。
