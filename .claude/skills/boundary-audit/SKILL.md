---
name: "boundary-audit"
description: "モード2: 境界監査(フェーズ2)。層と層の『境界(契約点)』で突き合わせる。FE↔BE(API契約)・BE↔Infra・Infra↔FE の整合を検査し、不整合のみ重大度(Blocker/High/Medium/Low)ソートの表で報告する。モジュール・境界単位で繰り返す。トリガー例『境界監査: <対象境界>』。"
argument-hint: "対象境界 / モジュール(例: 『1on1 機能の FE↔BE API 契約』)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# モード2: 境界監査(フェーズ2 / モジュール・境界ごとに繰り返し)

**まず `docs/code-review/policy.md` の「共通原則」「レイヤ↔実ディレクトリ対応」「正解情報の所在」を読むこと。**

各層を個別に見ず、層と層の「境界(契約点)」で突き合わせる。

## 毎回スコープを確定する

- 対象境界 / モジュール(例: 「Answers 機能の FE↔BE API 契約」)
- 対象ファイル群(モード1 の地図から特定)
- 参照する正解情報(OpenAPI / DB スキーマ / RLS / `packages/shared` DTO / `.env.example` / 規約)

## チェック観点

### FE(`apps/web`) ↔ BE(`apps/api` → answer-service)— API 契約
- パス / メソッド / req・res のフィールド名・型の一致
- TS 型 ⇔ DB・API スキーマの整合、enum・定数値の一致(**`packages/shared/src/dto/*`・`policy/*` が SSOT。FE と API が同じ DTO を使っているか**)
- バリデーション(クライアント ⇔ サーバ)の齟齬
- エラー形状・コード・HTTP ステータスの統一
- 認証 / 認可、トークン・セッションの扱い(**テナント/ユーザ識別は署名付き auth context 由来か。リクエストボディ上書きを許していないか**)
- 日時 / TZ / 数値精度、ページネーション規約
- camelCase(TS)⇔ snake_case(Python/DB)の変換漏れ

### BE ↔ Infra(`infra/`)
- env: 定義(`.env.example`)⇔ 使用(未定義参照・未使用定義)
- リソース名(DB / バケット / キュー / ベクトルストア): コード参照 ⇔ `infra/cdk` のプロビジョニング実体
- 権限: コードが呼ぶ API ⇔ 付与された IAM / RLS(`infra/db/migrations/postgres/*.sql`)の過不足
- リージョン / エンドポイント、CORS / ネットワーク、シークレットのハードコード
- DB マイグレーションの up/down 対称性・冪等性(`infra/db/migrations/postgres/`)

### Infra ↔ FE
- 公開 URL / ドメイン / CDN、CORS 許可オリジン ⇔ 実際の配信元(`aws-nextjs` same-origin 構成)
- 環境別 URL 差分(`NEXT_PUBLIC_API_BASE` 等)

## 進め方と出力

1. 対象境界の契約点を列挙
2. 各契約点の両側を突き合わせ、根拠 `file:line` を添える
3. 不整合のみ詳細報告、一致は要約のみ
4. 推測は `[推測]`、要確認は質問として残す

出力は重大度(Blocker / High / Medium / Low)でソートした表:

| # | 重大度 | レイヤ境界 | 不整合の内容 | 根拠(file:line) | 修正案 |

表の後に「整合が確認できた点」を簡潔に、最後に「要確認の未解決点」を質問形式で。
