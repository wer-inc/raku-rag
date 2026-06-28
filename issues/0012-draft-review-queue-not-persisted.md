# 0012 — AI ドラフトのレビューキューがプロセス内メモリで非永続(系統 ①)

> Priority: **P1 / High** / Status: Open / Labels: `manufacturing`, `persistence`, `review-queue`, `production`

## 背景(なぜ今)

レビューキュー(`GET /v1/manufacturing/drafts`)が返すドラフトは、本番でも **answer-service の
プロセス内 Python dict** に載っているだけ。再デプロイ/再起動・複数 Fargate タスクで**消える/共有されない**。
data-model §F は `DraftArtifact` をテナントスコープの永続エンティティと定義しており、**専用テーブルと
ORM モデルが既に存在するのに未使用**(dead code)。本番でレビュー中・承認済みドラフトが失われるのは
許容できない。

## 現状(根拠)

- `src/raku_rag/manufacturing/api/drafts.py:63` — `self._store: dict[tuple[str,str], DraftArtifact]`(in-memory)、
  `:64` `itertools.count(1)` で id 採番。create/list/get/assign/review はすべてこの dict を操作。
- `src/raku_rag/manufacturing/app.py:202-207` — `DraftService(...)` を**永続バックエンド指定なし**で構築。
- 本番合成 `build_manufacturing_system_for_base`(`src/raku_rag/production.py:487-494`)は
  **audit writer と policy store だけ** Postgres 化(`PostgresDataUsePolicyStore`)。DraftService はそのまま in-memory。
- **既に在る永続資産が死んでいる**:
  - テーブル `manufacturing_draft_artifacts`(migration `infra/db/migrations/postgres/0006_manufacturing_domain.sql`、
    down は `0006_..._domain.down.sql:7`)+ ORM モデル(`src/raku_rag/persistence/manufacturing_models.py:46,108`)。
  - grep 上、このモデルを read/write するコードが**どこにも無い**。
- 対比:文書承認メタは `set_meta`→registry/Postgres で永続化される(`ingestion/approval.py:220-227`)。
  ドラフトだけが揮発。

## 影響

- answer-service 再起動でレビューキューが空になり、in_review/approved ドラフトと監査の文脈が消える。
- 複数インスタンス間でキュー不整合(片方で承認、もう片方は未承認のまま)。
- フロントは server list 失敗時に per-browser localStorage へ暗黙フォールバック(→[0013](0013-review-badge-and-list-staleness.md))するため、
  障害が「空キュー」に見えて気づきにくい。

## 提案作業(何をどう対応)

1. **`PostgresDraftStore` を新設**(`PostgresDataUsePolicyStore` を雛形に、`src/raku_rag/persistence/` 配下):
   - `create/get/list/assign-update/review-update` を `manufacturing_draft_artifacts` テーブルに対して実装。
   - 既存スキーマ(0006)の列・CHECK 制約(状態 enum 等)に合わせる。id は DB 採番か ULID へ(itertools.count を廃止)。
   - テナントスコープ(RLS)を踏襲。`content` は jsonb。
2. **DraftService をストア注入式に**(`api/drafts.py`):
   現在の dict を `Protocol`(`DraftStore`)の InMemory 実装に切り出し、`__init__(store=...)` で差し替え可能に。
   テストは InMemory のまま、本番は Postgres。
3. **本番合成で配線**(`production.py:487-494` / `app.py:202-207`):
   DB 到達時は `PostgresDraftStore(base._conn)` を渡す(audit/policy と同じ条件分岐)。
4. **回帰テスト**:作成→answer-service 再起動→`GET /drafts` で同一 artifact が残る、2 接続で共有される、を
   `tests/postgres/` に追加(`live-smoke-catches-realpg-mfg-gaps` の手法)。

## 受け入れ条件(DoD)

- [ ] DB 到達環境でドラフト作成→answer-service 再起動後も `GET /v1/manufacturing/drafts` に出る。
- [ ] 2 プロセス/2 接続で同一テナントのキューが一致。
- [ ] in-memory ストアは単体テスト専用として残置(本番経路では使われない)。
- [ ] `manufacturing_draft_artifacts` が runtime で実際に read/write される(dead code 解消)。

## スコープ外

- ページング/トリアージ UI は [0013](0013-review-badge-and-list-staleness.md)。承認後の公開は [0019](0019-no-publish-path-after-approval.md)。

## 参照

- `src/raku_rag/manufacturing/api/drafts.py:48,62-64,116,196-200`, `app.py:202-207`, `production.py:487-494`
- `src/raku_rag/persistence/manufacturing_models.py:46,108` / `manufacturing_governance.py:28`(雛形)
- `infra/db/migrations/postgres/0006_manufacturing_domain.sql`, `specs/.../data-model.md §F`
