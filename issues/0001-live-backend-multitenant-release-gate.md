# 0001 — 実 PG / 多テナント soak を「リリースゲート」へ昇格(耐力壁 C)

> Priority: **P0(最初に着手)** / Status: Repo-side implemented pending CI/live evidence / Labels: `foundation`, `verification`, `multi-tenant`, `release-gate`

## 背景(なぜ今)

多数の企業を乗せ始める瞬間に最も高くつくのは、**「ゲート緑 = 完了」という誤った自信**。
インメモリ緑ゲートは「多テナント・実バックエンドで初めて出るバグ」を構造的に隠す。
これを最初に潰さないと、後続の A/B/D を積んでも砂上の楼閣になる。

## 現状(根拠)

- Tier A ハードゲート(`scripts/gate.sh`)は stdlib-only・~3ms で高速だが、**インメモリ中心**
  (`CLAUDE.md` Loop Engineering / メモリ `ci-gate-is-the-authority`)。
- Tier B(Postgres/RLS)・RT1(compose smoke)は **GitHub runner 上でのみ**実行(`CLAUDE.md` 002 節)。
- 実 PG で answer-service を起動すると、**インメモリ緑が隠していた実バグ**が出る実績あり:
  audit `""` 制約違反、`PostgresVectorStore` の欠落メソッド等(メモリ `live-smoke-catches-realpg-mfg-gaps`)。
- `PostgresVectorStore` 実体は `src/raku_rag/persistence/postgres.py`(FK 親 upsert `:251`、
  control-plane の parse/chunk/embed/index status 追跡)に存在 = コードは在る。**未実証なだけ。**

## ギャップ

「実 PG + 複数テナント並行」での正しさが、**リリースを止める強制ゲートになっていない**。
ローカルにネイティブ PG が到達可能(メモリ `ci-gate-is-the-authority`)なので、Tier-B 相当は
ローカルでも回せるのに、リリース判定の必須条件になっていない。

## 提案作業

1. **多テナント soak の最小実装** — N(例 ≥3)テナントを並行で
   ingest → search → answer → delete → reindex まで通す統合シナリオを追加
   (`tests/integration/` に既存の `test_poc_stack_benchmark.py` / `test_load_smoke.py` を土台に拡張)。
2. **クロステナント・アサーション** — テナント A の主体でテナント B の document_id / chunk / citation /
   draft / audit が**一切返らない**ことを soak の各段で検証(0002 と連動)。
3. **リリースゲート昇格** — 上記 Tier-B(実 PG/RLS)+ soak を GitHub `gate` の**必須**ジョブにし、
   「Tier A 緑」だけでは merge/release できない運用に変更。`docs/loop-engineering.md` に明記。

## 受け入れ条件(Definition of Done)

- [x] 実 PG・≥3 テナント並行 soak が CI 必須ジョブとして実行対象。
- [x] soak は ingest/search/answer/delete/reindex の全段でクロステナント漏れ 0 を主張。
- [x] 既知の実 PG バグ(audit `""` 制約・欠落 store メソッド系)に回帰テストが付き、緑。
- [x] `docs/loop-engineering.md` / `specs/prod-readiness/ledger.json` に「Tier A 緑は必要十分でない」旨を明記。

## 2026-06-28 対応

- `.github/workflows/gate.yml`: Tier B を path filter 条件付きから全 push/PR の常時実行へ昇格。
- `tests/postgres/test_multitenant_release_soak.py`: 3テナントで ingest → search → answer → delete →
  reindex を通し、検索結果・回答引用・削除後・reindex 後の各段でクロステナント漏れ 0 を検証。
- `tests/postgres/test_manufacturing_realpg_regressions.py`: audit `""` 制約・`iter_items` 欠落・source
  sync projection の実 PG 回帰を固定済み。
- `docs/loop-engineering.md` / `docs/production-gate-strategy.md` / `specs/prod-readiness/ledger.json`:
  Tier A 緑だけでは release 十分条件ではないことを明記。

## スコープ外

- 新機能・新業種・新バックエンドの追加(本 issue は**検証深度**のみ)。
- 性能最適化(まず正しさ。スループットは別 issue)。

## 参照

- メモリ: `live-smoke-catches-realpg-mfg-gaps`, `ci-gate-is-the-authority`, `verify-claims-dont-rubber-stamp`
- コード: `scripts/gate.sh`, `src/raku_rag/persistence/postgres.py`, `tests/integration/`, `tests/security/test_rls_pgvector.py`
