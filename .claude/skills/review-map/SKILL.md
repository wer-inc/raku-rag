---
name: "review-map"
description: "モード1: コードベースのマッピング(フェーズ0)。最初に1回だけ実行し、バグ指摘は一切せず構造把握に徹する。ディレクトリ構成・エントリポイント・依存関係・データフロー・データアクセス経路の全列挙・正解情報の所在・リスク集中箇所を出力し、末尾に『レビュー作業計画』を付ける。トリガー例『フェーズ0を実行』『コードベースを地図化して』。"
argument-hint: "対象スコープ(任意。未指定ならリポジトリ全体)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# モード1: マッピング(フェーズ0 / 最初に1回)

**まず `docs/code-review/policy.md` の「共通原則」と「正解情報の所在」を読むこと。** 用語(FE/BE/infra)の
実ディレクトリ対応表もそこにある。本リポジトリの層対応の要点:
FE=`apps/web` / BE=`apps/api`・`apps/answer-service`・`src/raku_rag`・`workers` /
共有契約=`packages/shared/src/{dto,policy}` / infra=`infra/{cdk,db,otel,localstack}`。

**この段階では一切バグ指摘をしない。構造把握に徹する。**

リポジトリ内を自分で探索し、以下を出力する。推測には `[推測]`、根拠に `file:line` を添える。

1. **ディレクトリ構成マップ**(FE / BE / infra ごとの主要モジュールと役割)
2. **各層のエントリポイント**(FE: ルーティング起点 `apps/web/app`・`middleware.ts` / BE: NestJS コントローラ `apps/api/src` と answer-service `apps/answer-service`・`src/raku_rag/app.py` / infra: `infra/cdk` の IaC 起点)
3. **モジュール境界と依存関係**(誰が誰を呼ぶか。層をまたぐ依存を特に明記。`packages/shared` の DTO/ポリシー型を誰が import するかは要注目)
4. **データフロー**(ユーザー操作 → `apps/web` → `apps/api` → answer-service/`src/raku_rag` → Postgres/pgvector・ベクトル検索・外部 LLM の経路)
5. **データアクセス経路の全列挙**(SQL クエリ / RLS / ORM スコープ / ベクトル検索 が走る場所すべて。`src/raku_rag/providers/vectorstores.py`・`core/tenancy.py`・`core/security/acl.py`・`infra/db/migrations/postgres/*.sql` を起点に網羅)
   ※ モード3(テナント分離)の起点になるので漏らさない
6. **正解情報の所在**(`docs/code-review/policy.md` の一覧を実在確認しつつ列挙。未発見は明記)
7. **リスク集中箇所の当たり**(境界・認可・テナント分離・RAG パイプライン)

**末尾に「レビュー作業計画」** を出力する。どの粒度で何回に分けてレビューすべきかを、モジュール /
境界 / PR の観点でリスト化する(後続のモード2・モード3 の実行計画になる)。各項目に推奨スキル
(`/boundary-audit` か `/tenant-audit`)を添える。

**禁止:** バグ修正案を出すこと。未探索ディレクトリについて断定すること。
