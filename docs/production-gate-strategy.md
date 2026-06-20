# 001 Production-Track Gate Strategy

002 で証明したループ（速く・信頼でき・ゲーム不可能な "No" を背骨に置く）を、**001 本番アダプタ**
（NestJS API / PostgreSQL+pgvector+RLS / SQS worker / OpenAPI）へ移植する。最大の論点は単純で——
**本番アダプタはゲートを重く・遅くする**。stdlib の 4ms gate（`scripts/gate.sh a`）のままでは回らない。
そこで「**速い層が大半の回帰を捕り、遅い層は選択的に回す**」よう gate を階層化する。

> 本筋の最初の一手は「API を作る」ではなく「**本番 track の L1 No を作る**」。本書がその設計。
> 既存の scaffolding: `infra/docker-compose.yml`(Postgres+pgvector+localstack), `apps/api`(NestJS),
> `workers/ingest/worker.py`, `packages/shared`, `pyproject [prod]`, 既存 `.github/workflows/ci.yml`。

---

## 中核原則: アダプタ・パリティ（これが移植を成立させる）

新しい本番ゲートをゼロから作らない。**002/001 の既存ハードゲート（ACL漏洩=0 / 削除再出現=0 /
テナント分離=0 / 6製造ゲート）の *アサーションをそのまま* 本番アダプタ（Postgres/pgvector）に
向けて回す**。fixture を `MvpSystem`(in-memory) ↔ `ProductionSystem`(Postgres-backed) で差し替えるだけ。

- 証明済みの "No" が**そのまま本番に転送**される（テストを書き直さない＝ゲームの隙が増えない）。
- 大半の検証ロジックは Tier A 速度のまま。本番依存は「同じアサーションを実バックエンドで」回す薄い層。
- 本番固有の追加ハードゲート: **RLS 分離**（application-path bypass role が無いこと）、**migration の
  前進/後退**、**deletion の物理カスケード**。これらだけが新規で、機構pin＋保護パス扱いは §5 と同じ。

---

## ゲート階層（Tier A–E）

| Tier | 何をgateするか | 依存 | 速度 | 実行 | 速く保つ要点 |
|---|---|---|---|---|---|
| **A** stdlib hard gate（現行） | ドメインロジック + in-memory での全ハードゲート | なし（stdlib） | ~ms | **常時**（local/全push/PR） | 既存 `gate.sh a`。**遅い検査をここに足さない**（内側ループの No） |
| **B** Postgres/pgvector/RLS contract + parity | スキーマ/migration、Document/Chunk/ACL repository 契約、**RLS分離**、pgvector retrieval、**既存security gateのPostgres版** | `infra/docker-compose.yml`(Postgres+pgvector) | 秒〜十数秒 | **PR**（+ local `gate.sh b`） | compose を**run毎に1回**起動（test毎でない）／session-scoped fixture／contract粒度（最小データ）／並列 |
| **C** SQS worker + ingestion integration | ingestion 永続化（SourceSyncState/IngestionRun/DocumentProcessingState）、diff-sync、worker のtenant context伝播 | compose(localstack SQS + Postgres + S3) | 十数秒〜分 | **PR（ingestion 触る変更）/ nightly** | 実 ingest を最小1縦串に絞る／queue は localstack |
| **D** NestJS API contract / OpenAPI | `/search` `/answer` `/ingest` の契約適合（schemathesis/OpenAPI）、auth middleware、tenant token | node + API 起動（+ B） | 数十秒 | **PR（apps/api 触る変更）** | 既存 `ci.yml` の node job を発展／契約テスト先行（full e2e は最小） |
| **E** full local production-like smoke | API+worker+DB+queue+storage を compose 全部立ち上げた end-to-end | compose 全部 | 分 | **nightly / pre-release**（`/schedule`） | 毎PRでは回さない。L4 連続ループ（読み取り）に相当 |

**判定式の拡張**（`docs/loop-engineering.md` §4 の `DONE(phase)`）: production フェーズの done は
`Tier A green ∧ 触れたアダプタの Tier(B/C/D) green ∧ 既存ハードゲートのparity green ∧ migration前進後退OK`。

---

## 速く保つ戦術（"No" が重くなりすぎない設計）

1. **Tier A は不可侵**。本番依存の検査を `gate.sh a` に足さない。内側ループは常に 4ms。
2. **compose は run毎に1回**。testcontainers / `docker compose up` をCI run単位 or session-scoped fixture で共有（test毎に立てない）。
3. **contract 先行 → integration 後**。アダプタは「インターフェース契約 × 実バックエンド × 最小データ」で先に速く検証し、重い full e2e（Tier C/E）は最小縦串に絞る。
4. **path-based gating**。PR が stdlib core だけなら Tier A、pgvector adapter を触れば A+B、apps/api を触れば A+(B)+D、ingestion を触れば A+B+C。**E は毎PRで回さない**。
5. **Tier 並列**。B/C/D は独立CIジョブとして同時実行（直列にしない）。
6. **§5 分離不変条件を継承**。本番ハードゲートテスト（RLS分離・deletion・tenant）も保護パス＋機構pin＋「既存ゲート改変＋src同時変更をブロック」。CI の separation job をそのまま拡張。

---

## 実装順（最小縦串）と Tier の解放

各ステップは「動くアダプタ」より先に「そのアダプタの No」を立てる。

1. **DB schema / migration / RLS の最小縦串** → **Tier B 解放**（migration前進後退 + RLS policy test。`infra/db/migrations/` は空＝最初の一手）。
2. **Postgres-backed Document/Chunk/ACL repository** → **Tier B parity**（既存 `tests/security/*` を Postgres-backed system に向けて回す＝ACL漏洩/削除/分離を実DBで再証明）。
3. **pgvector VectorStore adapter を既存 `RetrievalService` に差し込む**（`interfaces.VectorStore` 差し替え）→ **Tier B**（retrieval parity: 既存 recall/ACL pre-filter テストが pgvector で緑）。
4. **NestJS `/search` `/answer`** → **Tier D**（OpenAPI/契約。`apps/api` skeleton + `packages/shared` 契約を発展）。
5. **SQS worker（ingestion 永続化が見えてから）** → **Tier C**（`workers/ingest/worker.py` + localstack）。

> 要点: 1→2→3 は全て **Tier B（同一compose）** に乗る。つまり「Postgres+pgvector の No」を1つ立てれば
> repository・vector・RLS の3つが同じ速い層で回る。API(D)/worker(C) はその後。

---

## CI マッピング

- **現行** `.github/workflows/gate.yml`（Tier A、全push）はそのまま——内側ループの No。
- **Tier B/C/D** は PR で、`infra/docker-compose.yml` を `services:` or `docker compose up` で起動して回す（path filter で該当変更時のみ）。既存 `ci.yml`（python/security/node ジョブ）は Tier B/D の素地として発展・統合。
- **Tier E** は nightly（`/schedule`、L4 読み取り専用ループ）。
- 本番ハードゲート（RLS分離/migration/deletion）は §5 保護パスに追加。

---

## 次の具体的な一手

このゲート設計の次は「**Tier B を1つ立てる**」:
`infra/docker-compose.yml` で Postgres+pgvector を起動 → 最初の migration（schema + RLS policy）→
`gate.sh b`（Postgres前提で contract+parity を回す）→ **既存 `tests/security/*` を Postgres-backed
fixture で緑化**。これで「本番の L1 No」が立ち、002 で回したループがそのまま本番 track でも回る。
