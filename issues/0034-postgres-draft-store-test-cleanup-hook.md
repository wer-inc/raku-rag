# 0034 — Postgres draft store Tier B cleanup hook missing (系統 = qa / ci)

> Priority: **High** / Status: Addressed in PR #16 / Labels: `qa`, `ci`, `tier-b`, `postgres`, `review-queue`

## 背景(なぜ今)

PR #16 を `develop` に merge 可能な状態へ更新した後、GitHub Actions の Tier B
Postgres/pgvector/RLS job が `tests/postgres/test_draft_store_realpg.py` で失敗した。

## どんな課題か

- `TestPostgresDraftStoreDurability.setUp()` が `self.addCleanup(self._purge)` を呼ぶ。
- しかし `_purge` メソッドが存在せず、Postgres が利用可能な CI では全テストが
  `AttributeError` で落ちる。
- artifact id 指定の `_cleanup()` はあるが、setUp 直後や assertion failure 時に tenant 単位で
  orphan row を掃除する cleanup hook が欠けていた。

## どこで起きたか

- 画面: なし
- API: なし
- コード: `tests/postgres/test_draft_store_realpg.py`
- 環境: GitHub Actions `gate` / Tier B Postgres/pgvector/RLS
- run id / ingestion id / correlation id:
  - run: `28347487064`
  - job: `83973689481`
- 再現条件:
  - Postgres migrations 適用済み環境で `tests/postgres/test_draft_store_realpg.py` を実行する。

## 影響

- 営業デモへの影響: なし。
- 本番クライアントへの影響: なし。ただし release gate が赤くなり、PR を安全に merge できない。
- セキュリティ、監査、データ品質、UX への影響: Tier B の信頼性低下。テスト本体の tenant isolation
  以前に fixture cleanup hook で落ちるため、本来検証したい Postgres durability / RLS 信号が見えない。

## どう解決すべきか

1. `_purge()` を追加し、`self.tenant` と `self.other` それぞれの tenant context を設定して
   `manufacturing_draft_artifacts` を tenant 単位で削除する。
2. 既存の `_cleanup(*artifact_ids)` は個別テスト内の明示 cleanup として維持する。
3. Tier B CI で当該 test file が AttributeError なしに完走することを確認する。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- GitHub Actions の Tier B Postgres/pgvector/RLS job が当該 AttributeError で失敗しない。
- cleanup は tenant context を設定して実行され、別 tenant の draft row を消さない。
- 既存の安全ルール、ACL、監査要件を弱めていない。

## スコープ外

- PostgresDraftStore の production wiring 有効化。
- `manufacturing_draft_artifacts` の approved 制約修正。
- Tier B の緩和や skip 追加。

## 参照

- `tests/postgres/test_draft_store_realpg.py`
- GitHub Actions run `28347487064`, job `83973689481`
