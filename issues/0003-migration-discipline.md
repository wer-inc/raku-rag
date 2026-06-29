# 0003 — スキーマ/マイグレーション規律(耐力壁 B)

> Priority: **P1** / Status: Repo-side implemented pending CI/live evidence / Labels: `foundation`, `data-lifecycle`, `irreversible`, `ops`

## 背景(なぜ今)

多数テナントのデータが入った後、スキーマ変更は**稼働中の顧客データに対するオンライン移行**になる
(全社停止は不可)。これは規模が出た後に最も陰湿に効く。地味だが耐力壁。

## 現状(根拠)

- `src/raku_rag/migrations/` には `runner.py` と `__init__.py` のみ。**順序・バージョン登録
  (`schema_version` / applied-migrations レジストリ)が見当たらない**(grep ヒット 0)。
- 過去に**マイグレーション欠落事故**の実績(メモリ `live-fullstack-workspace` の「missing-0010-migration」)。
- `PostgresVectorStore` は FK 親(tenant→collection→document)を upsert してから子を書く設計
  (`persistence/postgres.py:251`)= スキーマ整合に敏感な構造。

## ギャップ

「順序付き・冪等・前方/後方互換・全テナント適用済みの証明」という**移行規律が仕組み化されていない**。
欠落・順序逆転・部分適用が静かに起こり得る。

## 提案作業

1. **順序付きマイグレーション + バージョンレジストリ** — 連番(0001..NNNN)+ `schema_migrations`
   テーブルで適用済みを記録。`runner.py` を「未適用分のみを順序通り・冪等に適用」する形へ。
2. **欠番/順序の CI チェック** — マイグレーション連番に穴・重複・順序矛盾があれば CI で落とす
   (過去の 0010 欠落型事故の再発防止)。
3. **前方/後方互換の規律** — expand→migrate→contract(列追加は nullable/default 付き、
   破壊的変更は2段階)を運用ルール化。`docs/` に1枚で明文化。
4. **全テナント適用の証明** — 移行後、全テナント(または全スキーマ/全 RLS 対象)に適用済みであることを
   検証するスモークを 0001 soak に追加。

## 受け入れ条件(Definition of Done)

- [x] `schema_migrations` 等のレジストリで「どの移行が適用済みか」を機械的に取得できる。
- [x] 連番の穴/重複/順序矛盾を CI が検出して落とす。
- [x] expand/contract の互換規律が `docs/` に明文化され、レビュー観点に入っている。
- [x] 「全テナント適用済み」を主張するスモークが緑(0001 と連動)。

## 2026-06-28 対応

- `tests/contract/test_migration_discipline.py`: Postgres migration の連番連続性、重複なし、全 up
  migration の down pair、`schema_migrations` レジストリ、migration smoke の自動 discovery を固定。
- `.github/workflows/gate.yml`: Tier B で全 numbered migration を実 Postgres に昇順適用し、全 down
  migration を逆順適用する smoke を追加。
- `scripts/postgres-migration-smoke.sh`: 手書き migration リストを廃止し、`infra/db/migrations/postgres`
  の全 numbered up migration を昇順適用、全 down migration を逆順適用する形に変更。
- `docs/migration-discipline.md`: contiguous numbering、down pair、expand→migrate→contract、Tier B
  release 判定のレビュー規律を明文化。
- `docs/loop-engineering.md` / `docs/production-gate-strategy.md`: release 境界では migration discipline
  を Tier B と合わせて見ることを明記。

## スコープ外

- ORM/マイグレーションツールの全面導入(まず軽量レジストリ + 規律。重い枠は不要)。
- マルチリージョン/シャーディング移行(将来)。

## 参照

- コード: `src/raku_rag/migrations/runner.py`, `src/raku_rag/persistence/postgres.py`
- メモリ: `live-fullstack-workspace`(missing-0010-migration), `ci-gate-is-the-authority`
