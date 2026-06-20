# Loop Engineering — raku-rag

このプロジェクトを「ループ」で進めるための単一の正典（SSOT）。Tier / L1–L4 / `/goal` /
不変条件 / 監督ケイデンス / ドライバ自動化ロードマップを、ここで機械判定可能な形に定義する。

> 中核原則: **ループの中に必ず「No と言える何か」（テスト・型・実エラー）を置き、それを
> *速く・信頼でき・ゲームできない* 形に保つ。** トラックA（stdlib先行）を選んだ理由は、この
> "No" を 4ms に保てるから。"No" が重く遅い実装（testcontainers/Postgres 前提）はループが回らない。

---

## 0. VISION（段階的ドライバ自動化）

最終到達点は「人がプロンプトを打つ」のをやめ、**エージェントにプロンプトを打つシステム（ドライバ）**を
持つこと。ただし安全ドメインなので **非安全ループのみ無人化し、安全境界は永久に有人**とする。

```
非安全ループ（L1 実装・L2 フェーズの一部）  → 自走（最終的に cron/driver で無人）
安全境界（ハードゲート設計・承認・safety state 変更） → 常に有人（自動化しない）
```

昇格条件（Stage を上げてよい＝ドライバに任せてよい判定）:

- **Stage 0（現在）**: 全ループ有人。人がプロンプトを承認/投入。
- **Stage 1 へ昇格**: `/goal` 式が **3フェーズ連続で機械判定どおり収束**し、§5 の分離不変条件が
  CI で強制され、§3 の機構テスト規約が全ハードゲートに適用済み → **非安全 L1 を無人化**。
- **Stage 2 へ昇格**: Stage 1 が **2週間 escalation なしで安定** → **非安全 L2 フェーズを driver/cron 化**。
- **不変**: いかなる Stage でも安全境界（§6 の禁止集合）は有人。L4 は常に読み取り専用。

---

## 1. ゲート定義 — 3 Tier（"No" の本体）

| Tier | 内容 | ループの扱い |
|---|---|---|
| **A 絶対ハードゲート（0容認）** | 001: ACLリーク=0 / 削除再出現=0 / テナント分離=0。002: SC-MFG-006/007/008/009/010/011（下表） | 1件でも失敗 → **即 HALT**。マージ禁止・「保留付きPASS」禁止 |
| **B 基準相対ゲート** | recall@k / citation_accuracy / groundedness / p95 latency / cost | 回帰 → ブロック。人間 override は理由を audit 記録 |
| **C 自動修正可** | ruff / black / mypy | ループ内で自動 fix |

**ゲート実行コマンド（単一）**: `scripts/gate.sh`（既定で Tier A、4ms・stdlib）。

### ハードゲート一覧（実装状況）

| Gate | SC | 検査の本質 | テストファイル | 状態 |
|---|---|---|---|---|
| ACL leak | base | 権限外文書が search/answer/citation に出ない（+肯定対照） | `tests/security/test_acl_leak.py` | ✅ 実装済 |
| Deletion | base SC-003 | 削除後 search=空 / answer=insufficient / cache無効化 | `tests/security/test_deletion_reappearance.py` | ✅ 実装済 |
| Tenant isolation | base | **事前フィルタ機構を pin**（post-filter は失敗させる）/ 存在開示なし | `tests/security/test_tenant_isolation.py` | ✅ 実装済（機構テストの手本） |
| Insufficient evidence | base SC-002 | 根拠なし → 推測せず insufficient | `tests/integration/test_insufficient_evidence.py` | ✅ 実装済 |
| High-risk safety | SC-MFG-006 | high-risk × approved引用欠如 → 断定しない | `tests/manufacturing/test_safety_gate.py` (T014) | ⬜ 未実装 |
| Obsolete/draft evidence | SC-MFG-011 | obsolete/draft を一次根拠にしない | `tests/manufacturing/test_obsolete_draft_evidence.py` (T015) | ⬜ 未実装 |
| Draft-only | SC-MFG-007 | AI生成物が draft 以外で自動確定されない | `tests/manufacturing/test_draft_only.py` (T039) | ⬜ 未実装 |
| ACL mapping | SC-MFG-008 | 全エンドポイントで権限外漏洩 0（001継承） | `tests/manufacturing/test_acl_mapping.py` (T052) | ⬜ 未実装 |
| No-train | SC-MFG-009 | opt-in無し学習0 / no-train非保証 capability は block | `tests/manufacturing/test_no_train.py` (T060) | ⬜ 未実装 |
| Audit coverage | SC-MFG-010 | 規定イベント記録率100% / PII混入0 | `tests/manufacturing/test_audit_coverage.py` (T061) | ⬜ 未実装 |

新ゲートが緑化したら **`scripts/gate.sh` の Tier A に編入**する（ゲートはこうして育てる）。

---

## 2. ループ層 L1–L4

| 層 | 何を回すか | 仕組み | 周期 | ゲート | 終了条件 | 人間 |
|---|---|---|---|---|---|---|
| **L1 内側TDD** | 1タスク(Txxx) | `/loop` 自走 / Workflow per-task pipeline | 分 | Tier A+C | 緑 & タスク受入基準 | 非安全=なし / **安全=ゲート設計は有人** |
| **L2 フェーズ** | Spec Kit 1フェーズ分 | **Workflow**（pipeline/parallel + バリア一括検証） | 時間 | full gate + code-review + security-review | フェーズ DONE 式（§4） | **境界で承認**（Phase2/9必須） |
| **L3 収束** | feature全体の取りこぼし | `/speckit-analyze` + `/speckit-converge`（loop-until-dry, K=2） | フェーズ末/日次 | converge が新タスクを出さない | 収束 | 追記タスク承認 |
| **L4 連続回帰** | main全体 | `/schedule` cron（**読み取り専用**） | 夜間 | full gate + eval baseline + security-review → レポート | — | 朝レポート確認のみ |

---

## 3. ハードゲート作成規約（ゲーム可能性への構造的対策）

**唯一の不文律: 出力ではなく「機構」を pin する。** 手本は `test_tenant_isolation.py` の
`test_case5_prefilter_boundary_not_postfilter`（`store.last_prefiltered_count == 1` を検査し、
post-filter 実装を*落とす*）。

- **肯定対照を必ず入れる**（「全部 deny で緑」を塞ぐ。例: `test_authorized_doc_is_visible`）。
- **fixture特異性を property-based で補う**（multi-doc / multi-group / Hypothesis）。既存3本の唯一の残存リスク。
- 002 ハードゲートは実装時に以下の機構テストを**必須**とする:
  - **T039 (draft-only)**: コード判定だけでは直INSERTで迂回可 → **DB CHECK制約**で縛り、テストは
    「`created_by=ai` を直接 approved に変更 → 制約違反で落ちる」ことを検査。
  - **T061 (audit 100% / PII=0)**: 「N個の手選びイベントが出た」は代理指標 → audit対象を
    **レジストリで閉じた列挙**にし全経路網羅 + 出力への**実PIIスキャナ**。
  - **T014 (high-risk)**: gate緑でも分類器の false negative（=危険）は素通り →
    **「必ず high-risk と判定すべきラベル付きクエリ集合」**を入れ、見落としを gate 失敗にする。

---

## 4. 収束条件 `/goal`（機械判定可能）

`/goal` は実コマンドではなく「フェーズ完了の機械判定式」。

```
DONE(phase P) :=
   gate.tierA == green              # 001の3本 + 緑化済み全002ハードゲート
 ∧ newHardGates(P) == green         # Pで新設したゲート（例 P=US1 → T014,T015）
 ∧ tasks(P).all(checked)            # tasks.md 当該フェーズ全タスク [x]
 ∧ analyze(P).inconsistencies == 0  # /speckit-analyze 不整合ゼロ
 ∧ tierB.regressions == 0           # baseline相対の回帰なし

ESCALATE(=人へ上げて停止) when:       # 「No」を止め時の定義にも使う
   tierA fail AND fixAttempts >= N            # 報酬ハック誘惑が起きる前に（既定 N=2）
 ∨ ゲート/テストを編集しないと緑にできない兆候   # ← §5 違反
 ∨ 分類器 / eval 回帰で方針判断が要る
 ∨ 001 Base-CR 依存でブロック
```

これにより「無限走行 vs 恣意的停止」が消え、止め時・人へ上げる時が式で決まる。

---

## 5. 不変条件: 検証と生成の分離

**ルール: 同一イテレーションで、ゲート/テストを緑化しながらそのファイルを編集してはならない。**
ゲート変更は別コミット + 人レビュー必須。報酬ハック（テストを緩めて緑）への唯一の保険。

enforce（多層・安価）:

- **(a) 保護パス**: `tests/security/**`, `tests/manufacturing/unit/**`, **6つのハードゲートテスト**（`test_safety_gate` / `test_obsolete_draft_evidence` / `test_draft_only` / `test_acl_mapping` / `test_no_train` / `test_audit_coverage`）, `scripts/gate.sh`
  → CI / `scripts/gate.sh separation` が「**既存**保護テストの改変 + `src/` 変更」を同時に弾く（新規ゲート追加は許可＝diff-filter=M）。※旧パターン `test_*gate*` は `test_safety_gate` 1本しか保護しない穴があり、6本全部へ拡張済み。
- **(b) CI は作業ツリーでなく `main` のテストでゲート判定** → ローカル改変で緑を偽装できない。
- **(c) L2 Workflow では実装エージェントにゲートファイルを read-only で渡す**。ゲート作成は
  人レビュー付きの独立フェーズに分離（implement→fix ループの中に入れない）。

---

## 6. 監督ケイデンス（予算 1〜2時間/日）

| ループ | 自律度 | 人間の関与 | レビュー対象 |
|---|---|---|---|
| L1 非安全 | 自走 | なし | — |
| L1 安全 | 実装は自走 / ゲート設計は有人 | テスト設計レビュー | §3 の機構テストになっているか |
| L2 フェーズ | 自走実装 | 境界で承認 | 差分 + code-review + security-review（Phase2/9必須） |
| L3 converge/analyze | 検出は自走 | 追記タスク承認 | converge追記の妥当性 / 不整合の解消方針 |
| L4 nightly | 完全自走（読み取り専用） | 朝レポート確認 | 回帰レポート。マージ/承認/安全state変更は禁止 |

**禁止集合（自動化しない＝常に有人）**: DraftArtifact 承認(SC-MFG-007) / high-risk 無根拠断定(006) /
obsolete・draft 一次証拠(011) / no-train override(009) / audit 抑制(010) / Constitution・eval回帰 override /
**ハードゲートのテストを書き換えて緑にする**。

---

## 7. 着手手順（現在地と次の一手）

- [x] `scripts/gate.sh`（Tier A 一本化、4ms）
- [x] `/speckit-analyze` プリフライト（002、読み取り専用 = L3 整合ゲート）— 完了 / 解決は §8
- [x] Phase 2 Foundational（T005/006/008/009/010/011）— L2 Workflow完了・gate GREEN(69)・32 unit tests・分離不変条件保持。T007(SQLAlchemy)/Dagster延期。要再確認(US1): value object 3件(TroubleCaseResult/HighRiskClassification/SafetyDecision)の tenant スコープ
- [x] US1（Phase 3: T012–T021 + 安全ゲート T014/T015）— L2 Workflow完了・gate.sh all GREEN・境界レビューPASS。§3 precision否定対照を追加、SafetyGate の非high-risk過剰ブロックを仕様準拠(FR-MFG-005/006)に修正
- [x] US2（Phase 4: DOCX/XLSX/CSV 取込・メタデータ・承認ライフサイクル）— L2 Workflow完了・gate.sh all GREEN(97)・境界レビューPASS（cell座標pin・imported approval優先を独立検証）。T002 deps導入、Dagster系(T024a/T031a/T031b)は本番adapter track延期
- [x] **PoC MVPコア(US1+US2)成立** — plan「MVP First」の STOP & VALIDATE 地点
- [x] US4（Phase 6: ドラフト生成 + レビュー, T038-T045）— 安全ハードゲート T039(SC-MFG-007 AI自動確定禁止)を機構pinで実装・境界レビューPASS（ai→approved経路の不在を実コードで確認、detached copy で直接変異も無効化）。**6ハードゲート中3本完了（006/007/011）**
- [x] US6（Phase 8: ACL マッピング, T052-T056）— セキュリティハードゲート T052(SC-MFG-008 権限外漏洩0)を001 pre-filter委譲で実装・境界レビューPASS（last_prefiltered_count で pre-filter機構pin・新authz無し）。**6ハードゲート中4本完了（006/007/008/011）**
- [x] Governance Overlay（Phase 9, T057-T065）— SC-MFG-009 no-train（opt-in強制・非no-train capability block＝temporarily_unavailable・no silent degrade）+ SC-MFG-010 audit（閉列挙網羅・PII0・SHA-256 hash chain改ざん検知）+ retention/policy/governance/export API + base-cr-notes。境界レビューPASS。**🎯 6ハードゲート全完成（006/007/008/009/010/011）**
- [x] US3（Phase 5: 類似トラブル事例, T032-T037）— 001 retrieval+ACL pre-filter再利用・Hard Rule 4（permanent過去事例も候補表示）機構pin・SC-MFG-008をtrouble-casesへ拡張。境界レビューPASS
- [x] US5（Phase 7: 運用ダッシュボード/KPI/safety telemetry, T046-T051）— SC-MFG-013 telemetry（相互排他・audit由来・冪等・factory/department軸）+ FR-MFG-028 KPI全項(json/csv)。境界レビューPASS。Dagster(T047a/T051a)延期
- [x] T066 PoC v0 縦串(end-to-end) + T067 quickstart S1-S11 — capstone統合検証PASS（225テスト）。**capstoneが実バグ発見・修正**: 多doc構成でobsoleteが一次引用されるSC-MFG-011抜けをanswer_ext.pyで降格修正（孤立fixtureのT015は捕捉できず＝§3 fixture特異性の実例）。Verifyで T070 セキュリティレビュー5軸PASS（PII0/draft/no-train/ACL/deletion）
- [x] T015 を多doc一次引用ケースで強化（capstone発見を専用 SC-MFG-011 ゲートに焼込・test-only・load-bearing）+ **§5分離ガードの保護対象を6ハードゲート全部に拡張**（旧 `test_*gate*` は `test_safety_gate` のみ保護の穴を修正、CIと整合）
- [x] T069 追加unit（classifier/正規化/2軸/承認/redaction, +61, 計287テスト）+ T068 docs（`docs/manufacturing/` 5本・コード忠実）— additive・src無変更・境界レビューPASS
- [x] T072 PoC 最小デモ（`poc-ui/` stdlib http.server）— 起動→curl で安全6挙動を実証・src無変更・gate covered。**🎯 002 = デモ可能な PoC v0 完成**
- [x] **002 freeze**。次の本筋 = 001 production track。**最初の一手は「API実装」でなく「本番trackのL1 No（ゲート）設計」** → `docs/production-gate-strategy.md`（Tier A–E・アダプタparity・compose Postgres+pgvector・実装順）
- [x] 001 production track **Step 2「Postgres parity」完成**: Tier B（migration/RLS/contract）+ Postgres-backed `ProductionSystem`（PostgresVectorStore/Registry/AclPolicy・ACL判定は Python の AclPolicy 再利用、tenant+tombstone+RLS は Postgres）。**既存 security ハードゲート（ACL漏洩 / tenant分離 incl. `last_prefiltered_count` / 削除再出現）が実Postgres+RLS に対し parity で green（CI tier-b）**。Tier A の 4ms ループ不変。ローカル PG14+pgvector 導入で高速ループ確立（`SET=%s`→`set_config` の実行差分を秒で潰した）
- [x] Step 3 **pgvector ランキング parity 完成**: search を `ORDER BY embedding <=> q`（cosine距離）へ移行、ACL は Python で **ranking後・top_k前**に適用（SQL LIMIT を ACL前に置かない＝可視行を切り捨てない）、`retrieval_score = 1 - distance`。in-memory MvpSystem を oracle に順位一致 + **top_k×ACL境界の敵対テスト**を CI tier-b で強制。security parity 無傷・Tier A 不変
- [x] Step 4a/4b **製品HTTP縦串 完成**: `web → NestJS /v1/answer(薄いfacade・認証/契約) → Python answer-service(/internal/answer) → ProductionSystem(Postgres+pgvector+RLS)`。**RAG真実は再実装せず**、テナント/identity は署名トークン由来（body無視）。最小 chat UI（tenant/user切替で ACL・テナント分離を可視化）。**Tier D**（facade契約 e2e: 認証必須 / tenant-from-token-not-body / forward+passthrough / 502）を CI 毎push強制。end-to-end 実証: `alice@demo` 接地回答+citation、クロステナント `bob@other` は漏洩なし

  縦串の起動（ローカルデモ）:
  ```
  POSTGRES_URL=postgresql://raku:raku@127.0.0.1:5432/raku_parity PYTHONPATH=src \
    python3 apps/answer-service/server.py --seed --reset-demo-db --port 8088  # 1) RAG真実(Postgresコア)
  ANSWER_SERVICE_URL=http://127.0.0.1:8088 API_PORT=3000 \
    npm run start --workspace @raku-rag/api                            # 2) NestJS facade(/v1/answer)
  npm run dev:web   # 3) tenant/user を切替えて ACL/テナント分離を確認
  ```
- [x] Step 5a **SQS worker runtime core 完成**: `InMemoryMessageQueue` + `SqsTaskQueue`（fake-client契約）、
  `IngestionWorker`（idempotency key・retry/DLQ・status projection）、`IngestionRunStore` +
  `PostgresIngestionRunStore`、Postgres `source_sync_states` / `ingestion_runs` /
  `document_processing_states` RLS tables。worker CLI は `--once` / `--drain` 対応。検証:
  `scripts/gate.sh all` GREEN（315 tests）, `npm run typecheck`, `npm run test:api`, shared build。
- [x] Step 4c **OpenAPI facade contract 公開**: `/v1/openapi.json` を追加し、health/whoami/answer の
  security/request/response schema を e2e で固定。検証: `npm run typecheck --workspace @raku-rag/api`,
  `npm run test:e2e --workspace @raku-rag/api`。
- [x] Step 4d **`/v1/search` facade 完成**: NestJS `POST /v1/search` が signed token 由来の
  tenant/user を使い、body tenant override を無視して Python `/internal/search` へ転送。Python
  internal search response は `SearchResponse`（source/version/freshness/correlation_id）形状で返す。
  OpenAPI に `/search` request/200 response schema を追加し、`tests/contract/test_search_answer.py`
  で `/answer` と合わせて固定。検証: `npm run typecheck`, `npm run test:api` GREEN（29 tests）,
  `scripts/gate.sh all` GREEN（319 tests, skipped 2）。
- [x] Step 4e **OpenAPI 全面契約テスト 完成**: `apps/api/scripts/export-openapi.cjs` で
  `/v1/openapi.json` と同じ document を JSON export し、`tests/contract/test_openapi.py` で全 `$ref`
  解決、operationId 一意性、public/protected security、path parameter 宣言、request/response schema、
  shared DTO 重要 shape を検証。Schemathesis は dev extra に追加し、現環境未導入時は smoke のみ skip。
  この gate で `AnswerResponse.used_chunks` の OpenAPI 不整合（string[]→UsedChunk[]）を修正済み。
  検証: contract 16 tests（1 skipped）, `scripts/gate.sh all` GREEN（328 tests, skipped 3）。
- [x] Step 4f **API versioning / deprecation headers 完成**: NestJS 起動時 middleware で
  URI version から `api-version` を全 response に付与し、`RAKU_API_V{n}_DEPRECATED` /
  `RAKU_API_V{n}_DEPRECATION` / `RAKU_API_V{n}_SUNSET` / `RAKU_API_V{n}_DEPRECATION_URL`
  で `Deprecation` / `Sunset` / `Link` を公開。CORS exposed headers と OpenAPI
  `components.headers` / 全 2xx response header contract も固定。検証: `npm run typecheck`,
  `npm run test:api` GREEN（31 tests）, contract 16 tests（1 skipped）,
  `scripts/gate.sh all` GREEN（328 tests, skipped 3）。
- [x] Step 4g **admin 設定 API 完成**: `/v1/admin/datasources`、
  `/query-profiles`（captioning toggle 含む）、`/provider-policies`（validate 含む）、
  `/retrieval-profiles`（benchmark stub 含む）、`/logging-policies`、`/acl`、`/budgets`
  を thin facade として追加。body の `tenant_id` override は facade で除去し、tenant/user は
  signed token 由来の internal header に固定。Python internal service は tenant-scoped 設定 store を持ち、
  ACL 追加は既存 `system.acl.add(...)`、tenant budget は既存 `CostService` に反映。OpenAPI は
  全 route/schema/2xx `api-version` header を contract 化。検証: `npm run typecheck`,
  `npm run test:api` GREEN（36 tests）, contract 17 tests（1 skipped）,
  `PYTHONPATH=src python3 -m py_compile apps/answer-service/server.py`,
  `scripts/gate.sh all` GREEN（329 tests, skipped 3）。
- [x] Step 4h **Python SDK client 完成**: `sdk/python/raku_rag_sdk` に stdlib-only
  `RakuRagClient` を追加。`/health`/`/openapi.json` public、search/answer/ingest、
  ingestion status/retry/delete、admin settings（datasources/query/provider/retrieval/logging/acl/budgets）
  helper を提供し、transport injection でテスト可能。ローカル開発用 `make_user_token` は NestJS
  facade と同じ HMAC `X-User-Token` 形式。検証:
  `PYTHONPATH=src python3 -m unittest tests.unit.test_python_sdk_client -v`,
  `python3 -m py_compile sdk/python/raku_rag_sdk/client.py sdk/python/raku_rag_sdk/__init__.py`,
  `scripts/gate.sh all` GREEN（334 tests, skipped 3）。
- [x] Step 5b-1 **S3/MinIO connector seam 完成**: `FileConnector` / `MemoryConnector` /
  `S3Connector` を `Connector.fetch(ref)` の同一境界に実装。`s3://bucket/key` と default bucket
  key を fake-client 契約で固定。検証: `tests.unit.test_connectors`。
- [x] Step 5b-2 **`/v1/ingest` facade 完成**: NestJS `POST /v1/ingest` が signed token 由来の
  tenant/user を使い、body tenant override を無視して Python `/internal/ingest` へ転送。Python
  internal service は connector seam で ref を fetch し、既存 `IngestionService` で index。OpenAPI
  に `/ingest` request/202 response schema を追加。検証: API e2e 22 tests + API typecheck。
- [x] Step 5b-3 **admin ingestion status/retry/delete facade 完成**: Python internal service が
  `IngestionRun` / `DocumentProcessingState` / `SourceSyncState` を RLS tenant context 付きで返し、
  NestJS `GET /v1/admin/sources/{source_id}/sync-status` /
  `/v1/admin/ingestion-runs/{ingestion_run_id}` /
  `/v1/admin/documents/{document_id}/processing-status` が signed token tenant を internal header に投影。
  `/internal/ingest` は直接実行時も `PostgresIngestionRunStore` に status projection を残す。加えて
  `GET /v1/admin/jobs?status=&source_id=`、
  `POST /v1/admin/ingestion-runs/{ingestion_run_id}/retry` と
  `DELETE /v1/admin/documents/{document_id}` を同じ thin facade で追加（削除は既存 `DeletionService`
  tombstone/cascade を再利用）。
  検証: `scripts/gate.sh all` GREEN（319 tests, skipped 2）, `npm run typecheck`,
  `npm run test:api` GREEN（29 tests）, `scripts/gate.sh separation`, `git diff --check`。
- [x] Step 5b-4 **reindex plan / admin reindex facade 完成**: `ReindexService` が新 version chunk を
  tombstone 状態で並行 build し、切替時に旧 chunk を tombstone、新 chunk だけ live に再 publish。
  失敗時は旧 version が引き続き検索可能。`InMemoryReindexPlanStore` と Dagster-compatible
  `src/raku_rag/dagster/jobs/reindex.py` shim を追加し、NestJS
  `POST /v1/admin/collections/{collection_id}/reindex` → Python
  `/internal/admin/collections/{id}/reindex` で `202 planned` を返す。SDK/OpenAPI/contract も更新。
  検証: `PYTHONPATH=src python3 -m unittest tests.integration.test_reindex tests.unit.test_reindex_backfill_job -v`,
  `npm run typecheck`, `npm run test:api` GREEN（37 tests）, contract 17 tests（1 skipped）,
  `scripts/gate.sh all` GREEN（337 tests, skipped 3）。
- [x] Step 5b-5 **backup/restore tombstone 再適用 完成**: `DeletionService` が削除時に
  `DeletionRecord` を保持し、`reapply_tombstones(tenant_id)` で復元後に live へ戻った document/chunk を
  再 tombstone + cache invalidate。検証:
  `PYTHONPATH=src python3 -m unittest tests.security.test_deletion_restore_reapply -v`,
  `scripts/gate.sh all` GREEN（338 tests, skipped 3）。
- [x] Step 5b-6 **ingestion executor helper / broken document retry 完成**:
  `IngestionExecutor` を `src/raku_rag/workers/ingestion.py` に追加し、SQS worker と future Dagster
  assets が同じ parse→chunk→embed→upsert 境界を使う形に統一。executor は content checksum /
  parser version / chunking config version / embedding model version を返し、IngestionRunStore と
  Postgres projection の `DocumentProcessingState` に反映。unsupported content type の壊れ文書は
  retry 後 DLQ へ移り、個別 document state に failure_reason と checksum/version が残る。
  検証: `PYTHONPATH=src python3 -m unittest tests.integration.test_ingest_queue tests.integration.test_ingest -v`,
  `scripts/gate.sh all` GREEN（339 tests, skipped 3）。
- [x] Step 5b-7 **Dagster-compatible ingestion assets / diff decision / source deletion path 完成**:
  `src/raku_rag/services/sync.py` に `SourceDocumentManifest` と `DiffDecisionService` を追加し、
  `src/raku_rag/dagster/assets/ingestion.py` に `source_manifest` / `changed_document_manifest` /
  `raw_document_artifacts` / `parsed_document_elements` / `chunks` / `embeddings` /
  `vector_index_entries` を実装。content checksum 不変は skip、approval metadata のみ変更は
  metadata/cache 更新のみ、parser/chunking version 変更は reparse/rechunk、embedding model 変更は
  reembedding/backfill 対象として判定。`deleted_in_source=true` は既存 `DeletionService` へ即時委譲し、
  tombstone/cache invalidation を physical cleanup 待ちにしない。検証:
  `PYTHONPATH=src python3 -m unittest tests.integration.test_diff_sync tests.integration.test_ingest_queue tests.unit.test_reindex_backfill_job tests.unit.test_sync_decisions tests.unit.test_dagster_ingestion_assets -v`,
  `scripts/gate.sh all` GREEN（349 tests, skipped 3）。
- [x] Step 5b-8 **Dagster project skeleton 完成**:
  `src/raku_rag/dagster/` に assets/resources/jobs/sensors/schedules/checks と
  tenant/collection/source/sync_run partition helper、Dagster run URL helper を配置。online
  answer/search path から `raku_rag.dagster` を import しない不変条件をテストで固定。検証:
  `PYTHONPATH=src python3 -m unittest tests.unit.test_dagster_skeleton tests.unit.test_dagster_ingestion_assets tests.unit.test_reindex_backfill_job -v`,
  `scripts/gate.sh all` GREEN（353 tests, skipped 3）。
- [x] Step 5b-9 **control-plane state repository 完成**:
  `src/raku_rag/persistence/control_plane.py` に SourceSyncState / SourceDocumentManifest /
  DocumentProcessingState / IngestionRun / AssetMaterializationRef / ReindexPlan の CRUD と
  app-facing source sync status projection を追加。in-memory `IngestionRunStore` も list/upsert/source
  sync projection を持つよう拡張。検証:
  `PYTHONPATH=src python3 -m unittest tests.unit.test_control_plane_repository tests.integration.test_ingest_queue tests.unit.test_dagster_ingestion_assets -v`,
  `scripts/gate.sh all` GREEN（356 tests, skipped 3）。
- [x] Step 5b-10 **answer/retrieval observability + token cost 完成**:
  `observability/tracing.py` / `metrics.py` / `audit.py` を追加し、AnswerService と RetrievalService が
  correlation_id 付き span、metrics、reference-only audit、embedding/LLM prompt/LLM completion token
  cost records を残す形に拡張。token records は budget 互換のため非課金、従来の answer cost/budget
  挙動は維持。検証:
  `PYTHONPATH=src python3 -m unittest tests.integration.test_answer_observability tests.integration.test_answer tests.integration.test_insufficient_evidence -v`,
  `scripts/gate.sh all` GREEN（358 tests, skipped 3）。
- [x] Step 5b-11 **text evaluation runner + security hard gate 完成**:
  `src/raku_rag/eval/models.py` / `runner.py` を追加し、EvaluationSet 登録時の PII/secret scrub、
  recall@k / citation accuracy / groundedness / p95 latency / query cost の text metrics、ACL leakage /
  deleted reappearance / tenant isolation / unauthorized context の absolute security hard gate を実装。
  security check が1件でも失敗すると `gate_result="blocked"`。検証:
  `PYTHONPATH=src python3 -m unittest tests.integration.test_eval tests.security.test_eval_hard_gate -v`,
  `scripts/gate.sh all` GREEN（361 tests, skipped 3）。
- [x] Step 5b-12 **CI eval gate / Dagster evaluation job / quality checks 完成**:
  `.github/workflows/ci.yml` に blocking `eval-gate` を追加し、
  `src/raku_rag/dagster/jobs/evaluation.py` に scheduled evaluation job helper、
  `src/raku_rag/dagster/checks/quality.py` に embedding coverage / chunk count / parser schema /
  spreadsheet cell range / deleted searchable / ACL / tenant isolation / baseline regression checks を追加。
  検証:
  `PYTHONPATH=src python3 -m unittest tests.unit.test_evaluation_job tests.unit.test_quality_checks tests.unit.test_ci_eval_gate tests.integration.test_eval tests.security.test_eval_hard_gate -v`,
  `scripts/gate.sh all` GREEN（365 tests, skipped 3）。
- [x] Step 5b-13 **eval/feedback API facade 完成**:
  `packages/shared/src/dto/eval.ts` / `feedback.ts` に共有 DTO を追加し、NestJS 側に
  `apps/api/src/eval/eval.controller.ts` と `apps/api/src/feedback/feedback.controller.ts` を実装。
  answer-service には internal evaluations/feedback endpoint と in-memory run store を追加し、
  eval set 登録時の redaction と evaluation runner 実行結果を API 経由で扱えるようにした。
  OpenAPI に `/evaluations/sets` / `/evaluations/runs` / `/evaluations/runs/{run_id}` / `/feedback`
  を追加。検証:
  `PYTHONPATH=src python3 -m py_compile apps/answer-service/server.py`,
  `npm run build:shared`, `npm run typecheck`, `npm run test:api`,
  `PYTHONPATH=src python3 -m unittest tests.integration.test_eval tests.security.test_eval_hard_gate -v`,
  `scripts/gate.sh all` GREEN（365 tests, skipped 3）,
  `scripts/gate.sh separation` GREEN,
  `git diff --check` GREEN。
- [x] Step 5b-14 **US5 observability dashboards / alerts / trace completeness / retry visibility 完成**:
  `MetricsRecorder` に stage-wise latency/throughput/error/cost 集計を追加し、
  `ops/dashboards/rag-platform-observability.json` を公開。`ops/alerts/rag-platform-alerts.json` と
  `observability/alerts.py` に ACL post-check diff / deletion reappearance / budget exceed / failed jobs /
  quality regression の alert catalog を追加。`IngestionService` / search / answer で correlation_id を
  span へ伝播し、answer には `generation.generate` span を追加。Dagster failed job 用には
  `workers/ingest/dagster/sensors/retry.py` で failed/dead_letter candidate と processing state の
  status reconciliation を検査し、admin job response に `dagster_run_url` を追加。検証:
  `PYTHONPATH=src python3 -m unittest tests.unit.test_observability_metrics tests.unit.test_alert_rules tests.integration.test_trace_completeness tests.unit.test_retry_sensor tests.integration.test_answer_observability -v`,
  `npm run build:shared`, `npm run typecheck`, `npm run test:api`,
  `scripts/gate.sh all` GREEN（370 tests, skipped 3）,
  `scripts/gate.sh separation` GREEN,
  `git diff --check` GREEN。
- [x] Step 5b-15 **foundation CI/API skeleton 棚卸し完了**:
  `.github/workflows/ci.yml` を lint → unit → contract → integration → security-hard-gate → eval-gate の
  明示ステップに整理し、T005 を完了化。NestJS `/v1` versioning、API key + HMAC `X-User-Token`
  middleware、principal propagation は既存 e2e で確認済みのため T020 を完了化。検証:
  `npm run build:shared`, `npm run typecheck`, `npm run test:api`,
  `scripts/gate.sh all` GREEN（370 tests, skipped 3）,
  `scripts/gate.sh separation` GREEN,
  `git diff --check` GREEN。
- [x] Step 5b-16 **US6 visual RAG thin path 完成**:
  `VisualAsset` / `LayoutRegion` / `OcrTextRegion` / `VisualCitation` domain 型、deterministic
  OCR/layout/captioning/visual embedding/VLM providers、visual ingestion executor、`LayoutRegion`→visual
  `Chunk` 変換 helper を追加。caption は retrieval aid として chunk text に含めるが、VLM は
  `primary_evidence_text`（OCR/layout region）だけを一次根拠に使う。AnswerService は visual evidence
  で VLM を使い、visual citation に asset/page/region/bbox/crop_uri を返す。EXIF は高リスク key を
  default strip、caption/OCR text は visual redaction hook を通す。CostService に OCR/layout/captioning/
  visual embedding/VLM image token/crop/storage cost kind を追加。visual ACL/deletion hard gate も既存
  pre-filter/tombstone path で固定。検証:
  `PYTHONPATH=src python3 -m unittest tests.integration.test_visual_answer tests.integration.test_visual_captioning_disabled tests.security.test_visual_acl_deletion tests.unit.test_visual_ingestion tests.unit.test_visual_providers tests.unit.test_visual_redaction tests.unit.test_visual_cost -v`,
  `scripts/gate.sh all` GREEN（387 tests, skipped 3）,
  `scripts/gate.sh separation` GREEN,
  `git diff --check` GREEN。残: assets endpoint、visual artifact/crop の永続 cascade。
- [x] Step 5b-17 **US6 crop inheritance + visual eval gate 完成**:
  `src/raku_rag/services/crop.py` に region crop 生成、tenant/collection/document/asset/region/bbox 継承、
  redaction policy 継承、document tombstone による crop 非表示を実装。DeletionService は crop store を
  受け取り、document delete/reapply tombstone 時に crop tombstone を伝播する。EvaluationRunner は
  `ExpectedEvidence` の visual asset/region/bbox を受け取り、visual_recall@k /
  visual_citation_accuracy / bbox_iou / visual_groundedness / p95 visual answer latency /
  visual query cost を算出し、visual ACL/deletion/unauthorized context/thumbnail-crop leakage を
  absolute hard gate に追加。AnswerService は visual answer 時に `vlm_image_tokens` を trace 付きで
  独立記録。検証:
  `PYTHONPATH=src python3 -m unittest tests.integration.test_eval tests.integration.test_visual_eval tests.security.test_eval_hard_gate tests.security.test_visual_eval_hard_gate tests.integration.test_visual_answer tests.integration.test_visual_captioning_disabled tests.unit.test_visual_cost tests.unit.test_crop_service tests.security.test_visual_acl_deletion -v`,
  `scripts/gate.sh all` GREEN（391 tests, skipped 3）。当時残: assets endpoint、visual artifact/thumbnail まで含む
  永続 cascade（assets endpoint は Step 5b-18 で完了）。
- [x] Step 5b-18 **US6 assets endpoint 完成**:
  `AssetService` を追加し、visual asset id から authorized visual chunks / inherited crops を解決。
  ACL 不能・削除済み・存在なしは同じ 404 相当で閉じる。MVP/Postgres vector store に
  `visual_chunks_for_asset` を追加し、Postgres ACL は direct document read 判定でも grant を読むよう修正。
  answer-service に `GET /internal/assets/{asset_id}`、NestJS facade に `GET /v1/assets/{asset_id}`、
  shared DTO / OpenAPI / e2e contract を追加。検証:
  `PYTHONPATH=src python3 -m py_compile src/raku_rag/services/assets.py src/raku_rag/providers/vectorstores.py src/raku_rag/persistence/postgres.py src/raku_rag/app.py src/raku_rag/production.py apps/answer-service/server.py`,
  `PYTHONPATH=src python3 -m unittest tests.unit.test_assets_service tests.unit.test_crop_service tests.security.test_visual_acl_deletion tests.contract.test_search_answer -v`,
  `npm run build:shared`, `npm run typecheck`, `npm run test:api`,
  `scripts/gate.sh all` GREEN（393 tests, skipped 3）。当時残: visual artifact/thumbnail まで含む永続 cascade。
- [x] Step 5b-19 **US6 visual deletion cascade 完成**:
  `CacheService` を document 依存に加えて visual asset/crop 参照でも invalidate できるよう拡張。
  InMemory/Postgres vector store に `visual_chunks_for_document` を追加し、DeletionService が purge 前に
  visual asset/region/crop refs を収集して、document tombstone、visual chunk/OCR/generated caption/
  visual embedding purge、crop tombstone、thumbnail/VLM/crop cache invalidation を一括 cascade する。
  `DeletionResult` と delete API response には visual cascade counters を追加。restore 後の
  `reapply_tombstones` でも visual cache を再無効化する。検証:
  `PYTHONPATH=src python3 -m py_compile src/raku_rag/services/cache.py src/raku_rag/services/deletion.py src/raku_rag/providers/vectorstores.py src/raku_rag/persistence/postgres.py apps/answer-service/server.py`,
  `PYTHONPATH=src python3 -m unittest tests.security.test_visual_deletion_cascade tests.security.test_visual_acl_deletion tests.security.test_deletion_reappearance tests.security.test_deletion_restore_reapply tests.unit.test_assets_service tests.unit.test_dagster_ingestion_assets -v`,
  `npm run build:shared`, `npm run typecheck`, `npm run test:api`,
  `scripts/gate.sh all` GREEN（395 tests, skipped 3）。US6 T063-T079 は完了。
- [x] Step 5b-20 **Polish T080-T085 完成**:
  `docs/rag-platform-architecture.md` / `docs/provider-replacement-guide.md` /
  `docs/api-examples.md` を追加し、13 provider 抽象、security invariant、API 使用例を文書化。
  quickstart S1-S10 integration を `tests/integration/test_quickstart.py` に追加し、grant →
  text ingest/search/answer → insufficient evidence → unauthorized fail-closed → visual ingest/answer/assets →
  text+visual eval → deletion を一気通しで検証。`tests/unit/test_core_quality.py` で日本語 chunk
  boundary/offset、ACL、groundedness、text/visual/EXIF redaction を追加。`tests/security/test_redaction.py`
  で logs/audit/eval/OCR/caption/EXIF/crop の secret/PII 非保存を hardening review として固定し、
  visual ingestion の OCR redaction も実装。`Settings` に p95/visual p95/throughput/concurrency/
  max document/max chunk knobs と env loader を追加。`eval/baseline.py` と
  `tests/fixtures/eval/baseline.json` で text+visual baseline regression gate を追加し、
  `.github/workflows/ci.yml` の eval-gate を visual/security/baseline まで拡張。検証:
  `PYTHONPATH=src python3 -m py_compile src/raku_rag/core/config.py src/raku_rag/eval/baseline.py src/raku_rag/eval/__init__.py src/raku_rag/workers/ingestion.py`,
  `PYTHONPATH=src python3 -m unittest tests.unit.test_core_quality tests.security.test_redaction tests.unit.test_eval_baseline_gate tests.unit.test_config_logging_default tests.unit.test_ci_eval_gate tests.integration.test_quickstart tests.integration.test_visual_answer tests.integration.test_visual_eval tests.security.test_visual_acl_deletion tests.contract.test_docs -v`,
  `npm run build:shared`, `npm run typecheck`, `npm run test:api`,
  `scripts/gate.sh all` GREEN（408 tests, skipped 3）。
- [x] Step 5b-21 **Setup scaffold T002/T004 完成**:
  `infra/cdk/` に TypeScript CDK app scaffold（`cdk.json`, `bin/raku-rag.ts`,
  `lib/raku-rag-stack.ts`, package/tsconfig/README）を追加し、既存 NestJS API / Next.js web /
  Python worker / shared contracts と合わせて monorepo 初期化を完了。ルート `docker-compose.yml` を追加し、
  `docker compose up` だけで Postgres+pgvector / MinIO / LocalStack SQS が立ち、profile で
  Langfuse / Redis / Dagster dev UI を足せる形にした。`infra/docker-compose.yml` にも Dagster profile を追加。
  `tests/conftest.py` には pytest/testcontainers 用の Postgres / LocalStack SQS / MinIO / Redis fixture を追加し、
  `tests/unit/test_setup_scaffold.py` で scaffold contract を固定。検証:
  `PYTHONPATH=src python3 -m py_compile tests/conftest.py tests/unit/test_setup_scaffold.py`,
  `PYTHONPATH=src python3 -m unittest tests.unit.test_setup_scaffold tests.unit.test_repo_layout tests.integration.test_stack_boot -v`,
  `npm run build:shared && npm run typecheck --workspaces --if-present`,
  `scripts/gate.sh all` GREEN（412 tests, skipped 3）,
  `git diff --check` GREEN。Docker はこの環境の PATH に無いため compose 実起動/Tier B は未実行。
- [x] Step 5b-22 **ProviderPolicy T086/T087 完成**:
  `workers/ingest/provider_policy.py` に fail-closed な `ProviderPolicyEnforcer` を追加し、
  parser/OCR/LLM/embedding/rerank ごとの allowlist、AWS-only parser mode、region、zero-retention、
  no-train、customer opt-in、fallback provider を判定。answer-service の
  `/internal/admin/provider-policies/{id}/validate` は同じ contract で Azure Document Intelligence /
  Google Document AI を既定 AWS-only から拒否する。NestJS 側は provider policy routes を
  `apps/api/src/admin/provider-policies.controller.ts` と `apps/api/src/provider-policy/provider-policy.service.ts`
  に分離し、shared DTO/OpenAPI に OCR allowlist と `operation: "ocr"` を追加。検証:
  `PYTHONPATH=src python3 -m py_compile workers/ingest/provider_policy.py apps/answer-service/server.py tests/contract/test_provider_policies.py`,
  `PYTHONPATH=src python3 -m unittest tests.contract.test_provider_policies -v`,
  `npm run build:shared && npm run typecheck --workspaces --if-present`,
  `npm run test:api` GREEN（45 tests）,
  `scripts/gate.sh all` GREEN（417 tests, skipped 3）,
  `git diff --check` GREEN。
- [x] Step 5b-23 **RetrievalProfile T088-T090 完成**:
  `apps/api/src/retrieval/identifier-match.ts` に normalized exact/prefix 用 identifier matcher を追加し、
  equipment_id / alarm_code / property_id / room_number / contract_id / fund_id / ISIN / invoice_id を標準 field とした。
  `apps/api/src/retrieval/retrieval-profile.service.ts` は metadata exact + identifier exact + pgvector candidate を
  union し、rerank candidate を 80 以下に bound、final context limit で切る。vector-only profile は
  `vector_only_disabled` で fail-closed。RetrievalProfile API は
  `apps/api/src/admin/retrieval-profiles.controller.ts` に切り出し、GET/PUT/benchmark endpoint を維持。
  contract/e2e で route、candidate union、identifier normalization、vector-only 禁止を固定。検証:
  `PYTHONPATH=src python3 -m unittest tests.contract.test_retrieval_profiles -v`,
  `npm run build:shared && npm run typecheck --workspaces --if-present`,
  `npm run test:api` GREEN（48 tests）,
  `scripts/gate.sh all` GREEN（421 tests, skipped 3）,
  `git diff --check` GREEN。
- [x] Step 5b-24 **Schema/RLS hardening T008/T091/T092 完成**:
  `infra/db/migrations/postgres/0002_policy_profile_visual_rls.sql` を追加し、
  visual_assets/layout_regions/crops、embeddings（target_type/modality + pgvector hnsw）、
  cost_records/budgets、source_document_manifests、asset_materialization_refs、reindex_plans、
  provider/retrieval/logging policies、embedding_jobs、rerank_traces、provider_config_audit_events、
  evaluation_runs を tenant scoped + RLS FORCE で定義。Document/Chunk 既存 metadata_schema_version に加えて
  VisualAsset/LayoutRegion metadata_schema_version、caption/crop fields、policy lifecycle fields、
  document hot metadata index と identifier hot-field expression index も contract 化。
  `tests/contract/test_schema_lock_migration_sql.py` で schema lock を静的検査し、
  `tests/security/test_rls_pgvector.py` で RLS/session tenant/no BYPASSRLS/pgvector tombstone index と
  cross-tenant vector-search parity を hard gate に追加。検証:
  `PYTHONPATH=src python3 -m unittest tests.contract.test_schema_lock_migration_sql tests.security.test_rls_pgvector -v`,
  `scripts/gate.sh a` GREEN,
  `scripts/gate.sh all` GREEN（431 tests, skipped 3）,
  `git diff --check` GREEN。Docker がこの環境の PATH に無いため `scripts/gate.sh b` の実 DB 適用は未実行。
- [x] Step 5b-25 **Embedding/chunking T093/T094 完成**:
  `workers/ingest/providers/embeddings/bedrock_cohere.py` に Cohere Embed Multilingual v3 の Bedrock provider を追加し、
  1024 次元・max input 512 tokens・zero-retention/no-train capability を contract 化。入力過大時は
  Bedrock 呼び出し前に `RechunkRequired` と `RechunkPlan(target_tokens=350, max_tokens=450)` で fail-closed。
  `workers/ingest/chunking/` には 250-400 token target / max 450 の chunker default を追加し、
  heading_path と metadata を本文から分離、XLSX/CSV 用に table summary / row / cell chunk を生成する。
  検証:
  `PYTHONPATH=src python3 -m py_compile workers/ingest/providers/embeddings/bedrock_cohere.py workers/ingest/chunking/__init__.py tests/unit/test_bedrock_cohere_embedding.py tests/unit/test_worker_chunking.py`,
  `PYTHONPATH=src python3 -m unittest tests.unit.test_bedrock_cohere_embedding tests.unit.test_worker_chunking -v`,
  `black workers/ingest/providers/embeddings/bedrock_cohere.py workers/ingest/chunking/__init__.py tests/unit/test_bedrock_cohere_embedding.py tests/unit/test_worker_chunking.py && ruff check workers/ingest/providers/embeddings/bedrock_cohere.py workers/ingest/chunking/__init__.py tests/unit/test_bedrock_cohere_embedding.py tests/unit/test_worker_chunking.py`,
  `scripts/gate.sh all` GREEN（436 tests, skipped 3）,
  `git diff --check` GREEN。
- [x] Step 5b-26 **Bedrock Cohere rerank T095 完成**:
  `apps/api/src/rerank/bedrock-cohere-rerank.service.ts` を追加し、Cohere Rerank 3.5
  (`cohere.rerank-v3-5:0`) を Bedrock Runtime `invokeModel` 経由で呼ぶ adapter を実装。
  入力候補は 50-80 件の範囲に bound し、final context は 5-12 件の範囲で切る。
  response score は `chunk_id` keyed trace に残し、latency / candidate_count / final_context_count /
  optional cost_record_id を `RerankTrace` として記録。Bedrock client 未設定・呼び出し失敗時は
  rerank を `skipped` として、bounded candidate order を維持する fallback に閉じる。NestJS AppModule に
  provider 登録し、`apps/api/test/rerank.e2e-spec.ts` と
  `tests/contract/test_bedrock_cohere_rerank.py` で request shape / bounds / cost+latency trace /
  skip fallback を固定。検証:
  `PYTHONPATH=src python3 -m py_compile tests/contract/test_bedrock_cohere_rerank.py`,
  `black tests/contract/test_bedrock_cohere_rerank.py && ruff check tests/contract/test_bedrock_cohere_rerank.py`,
  `PYTHONPATH=src python3 -m unittest tests.contract.test_bedrock_cohere_rerank -v`,
  `npm run test:api -- --runInBand rerank.e2e-spec.ts && npm run typecheck --workspace @raku-rag/api`,
  `git diff --check` GREEN。
- [x] Step 5b-27 **Bedrock Claude T096 完成**:
  `apps/api/src/llm/bedrock-claude.service.ts` を追加し、Bedrock Claude Messages API 用の
  injectable provider を実装。final answer は Sonnet 既定
  (`anthropic.claude-sonnet-4-6`) に、classification / enrichment / summarization /
  high-risk assistance は Haiku-class 既定 (`anthropic.claude-haiku-4-5-20251001-v1:0`) に分離。
  モデル ID は `BEDROCK_CLAUDE_SONNET_MODEL_ID` / `BEDROCK_CLAUDE_HAIKU_MODEL_ID` で差し替え可能。
  `anthropic_version: "bedrock-2023-05-31"` の Bedrock Runtime `invokeModel` payload、usage tokens、
  latency、optional cost record、prompt template version を trace 化。client 未設定は
  `bedrock_claude_client_not_configured` で fail-closed。NestJS AppModule に provider 登録し、
  `apps/api/test/llm.e2e-spec.ts` と `tests/contract/test_bedrock_claude.py` でモデル振り分け /
  request shape / token+cost trace / env override を固定。検証:
  `PYTHONPATH=src python3 -m py_compile tests/contract/test_bedrock_claude.py`,
  `black tests/contract/test_bedrock_claude.py && ruff check tests/contract/test_bedrock_claude.py`,
  `PYTHONPATH=src python3 -m unittest tests.contract.test_bedrock_claude -v`,
  `npm run test:api -- --runInBand llm.e2e-spec.ts app.e2e-spec.ts && npm run typecheck --workspace @raku-rag/api`,
  `git diff --check` GREEN。
- [x] Step 5b-28 **Bedrock Guardrails T097 完成**:
  `apps/api/src/guardrails/bedrock-guardrails.adapter.ts` を追加し、Bedrock Guardrails
  `ApplyGuardrail` 用の input/output adapter を実装。`GUARDRAIL_INTERVENED` は補助ブロックとして扱い、
  client / guardrail 未設定時は `UNAVAILABLE` として記録するが、primary control を広げない。
  `enforcePrimaryControls` は ACL / RequiredEvidencePolicy / GroundednessGate / RiskGate の block を
  常に guardrail allow より優先し、`bypassCapabilities()` と `bypassesPrimaryControls(): false` で
  defense-in-depth only contract を明示。NestJS AppModule に provider 登録し、
  `apps/api/test/guardrails.e2e-spec.ts` と `tests/security/test_guardrails_adapter.py` で
  request shape / intervention / primary-control non-bypass / unavailable 時の非拡張を固定。検証:
  `npm run typecheck --workspace @raku-rag/api`,
  `npm run test:api -- --runInBand guardrails.e2e-spec.ts app.e2e-spec.ts`,
  `PYTHONPATH=src python3 -m py_compile tests/security/test_guardrails_adapter.py`,
  `black tests/security/test_guardrails_adapter.py && ruff check tests/security/test_guardrails_adapter.py && PYTHONPATH=src python3 -m unittest tests.security.test_guardrails_adapter -v`,
  `git diff --check` GREEN。
- [x] Step 5b-29 **LoggingPolicy/Langfuse T098/T099 完成**:
  `apps/api/src/observability/logging-policy.service.ts` に `LoggingPolicyEnforcer` を追加し、
  Langfuse trace payload を policy で sanitize。`raw_retrieved_context_storage` は default `disabled`、
  raw query / retrieved context / model input / model output は disabled / redacted / full_opt_in を明示解釈し、
  secret は full opt-in 時も redaction。citation IDs、chunk IDs、document IDs、prompt template version、
  model metadata、latency、cost は policy flag に従って保持する。`production_sampling_rate` は
  deterministic sampling で enforcement。`apps/api/src/observability/langfuse.ts` に exporter を追加し、
  sanitized event のみ送信、sampled-out / client 未設定 / export failure は answer path を壊さない status で返す。
  NestJS AppModule に `LoggingPolicyEnforcer` / `LangfuseExporter` を provider 登録。
  `apps/api/test/observability.e2e-spec.ts` と `tests/security/test_logging_policy.py` で、Langfuse default が
  raw context を保存しないこと、参照 ID / prompt version / model / latency / cost が残ること、redaction /
  sampling / export failure を固定。検証:
  `npm run typecheck --workspace @raku-rag/api`,
  `npm run test:api -- --runInBand observability.e2e-spec.ts app.e2e-spec.ts`,
  `PYTHONPATH=src python3 -m py_compile tests/security/test_logging_policy.py`,
  `black tests/security/test_logging_policy.py && ruff check tests/security/test_logging_policy.py && PYTHONPATH=src python3 -m unittest tests.security.test_logging_policy -v`,
  `git diff --check` GREEN。
- [x] Step 5b-30 **Parser provider policy T102/T103 完成**:
  `workers/ingest/providers/parsers/` に ProviderPolicy-gated parser adapters を追加。
  customer-managed / OSS(Tesseract) / AWS Textract / Azure Document Intelligence / Google Document AI を
  共通 `ParserProviderAdapter` と `ProviderPolicyParserRouter` 配下に置き、policy 評価が通るまで
  raw bytes を provider client へ渡さない順序を固定。拒否時は policy fallback → customer-managed →
  OSS の順に再評価し、許可された fallback のみ raw を受け取る。`ParserProviderAuditEvent` は
  provider decision / fallback / raw_content_sent を記録し、理由は redacted。`tests/integration/test_parser_provider_policy.py`
  で AWS-only default の Azure/Google raw-send 0、Azure opt-in+region+zero-retention+no-train 成功、
  capability/residency 違反時 fallback、Textract opt-in 成功、fallback 不在時 fail-closed を固定。検証:
  `PYTHONPATH=src python3 -m py_compile workers/ingest/providers/parsers/__init__.py tests/integration/test_parser_provider_policy.py`,
  `black workers/ingest/providers/parsers/__init__.py tests/integration/test_parser_provider_policy.py && ruff check workers/ingest/providers/parsers/__init__.py tests/integration/test_parser_provider_policy.py`,
  `PYTHONPATH=src python3 -m unittest tests.integration.test_parser_provider_policy -v`,
  `git diff --check` GREEN。
- [x] Step 5b-31 **ProviderConfigAuditEvent T104 完成**:
  `src/raku_rag/persistence/provider_config_audit.py` に tenant-scoped audit repository を追加し、
  provider / retrieval / logging / query model / parser policy 変更の before/after snapshot を再帰 redaction して記録。
  answer-service の admin settings store は `parser_provider_changed` / `residency_override` /
  `opt_in_changed` / `model_changed` / `retrieval_profile_changed` / `logging_policy_changed` を発火し、
  `audit_events` と `provider_config_audit_event_id` を mutation response に付与。`GET
  /v1/admin/provider-config-audit-events` を NestJS facade と OpenAPI に追加し、event_type /
  correlation_id / collection_id filter を answer-service へ転送。`packages/shared` の DTO も
  `redacted_before` / `redacted_after` と新 event types を固定。検証:
  `PYTHONPATH=src:. python -m unittest tests.integration.test_provider_config_audit tests.contract.test_provider_config_audit tests.contract.test_provider_policies`,
  `npm run build:shared`,
  `npm run test:api -- --runInBand admin-settings.e2e-spec.ts` GREEN。
- [x] Step 5b-32 **PoC stack benchmark harness T105 完成**:
  `tests/benchmarks/poc_stack_benchmark.py` に二段 PoC benchmark harness を追加。製造業 /
  不動産管理 / 投資運用・投信の industry profile ごとに 20〜50 件の deterministic Japanese
  document samples を生成し、PDF/DOCX/XLSX/CSV/image/scanned PDF の source format をカバー。
  Stage 1 は parser/provider matrix（Textract / Azure DI / Google DI / OSS）と
  parser_table_structure_accuracy / spreadsheet_cell_citation_accuracy / ProviderPolicy compliance 等を定義。
  Stage 2 は embedding model × retrieval profile matrix と recall@5/10 / exact code lookup /
  citation / groundedness / high-risk gate / latency / cost を定義。`run_offline` は evaluator override を受け取り、
  後続 T106-T109 の実測差し替え口と OpenAPI の `poc_stack_benchmark` summary shape を返す。
  `tests/integration/test_poc_stack_benchmark.py` と `tests/contract/test_poc_stack_benchmark.py` で
  20/50 sample bounds、三業種 corpus、Stage 1/2 matrix、hard gates、fallback paths を固定。検証:
  `python -m black tests/benchmarks/poc_stack_benchmark.py tests/integration/test_poc_stack_benchmark.py tests/contract/test_poc_stack_benchmark.py`,
  `PYTHONPATH=src:. python -m ruff check tests/benchmarks/poc_stack_benchmark.py tests/integration/test_poc_stack_benchmark.py tests/contract/test_poc_stack_benchmark.py`,
  `PYTHONPATH=src:. python -m unittest tests.integration.test_poc_stack_benchmark tests.contract.test_poc_stack_benchmark` GREEN。
- [x] Step 5b-33 **PoC benchmark details T106-T109 完成**:
  `tests/benchmarks/poc_stack_benchmark.py` の offline benchmark を T106-T109 の比較粒度まで拡張。
  T106: Stage 1 parser/provider 結果に `format_results` を追加し、PDF/DOCX/XLSX/CSV/image/scanned PDF
  ごとに Azure DI / Google DI / Textract / OSS(Tesseract) の parser_table_structure_accuracy、
  spreadsheet_cell_citation_accuracy、OCR/layout confidence、latency/cost、ProviderPolicy compliance を比較。
  T107: Stage 2 retrieval matrix に `hybrid_metadata_code_vector_rerank` を追加し、
  Cohere Embed Multilingual v3 / Titan と vector+rerank / metadata+code+vector+rerank / hybrid を
  recall@5/10、exact code lookup、citation で比較。T108: retrieval 結果に `query_type_metrics` と
  run-level `answer_quality_results` を追加し、exact code lookup / spreadsheet cell citation /
  high-risk gate の品質を citation accuracy、groundedness、insufficient-evidence rejection、
  high-risk compliance、p95 latency、query cost で集約。T109: `SECURITY_PROBES` と
  `security_results` を追加し、ACL leakage / tenant leakage / deleted document searchable /
  raw context logging violation の count が 0 でない run は `blocked`。外部クラウド実測は evaluator
  override で差し替える設計にし、CI では deterministic offline benchmark を固定。検証:
  `PYTHONPATH=src:. python -m unittest tests.integration.test_poc_stack_benchmark tests.contract.test_poc_stack_benchmark`,
  `PYTHONPATH=src:. python -m ruff check tests/benchmarks/poc_stack_benchmark.py tests/integration/test_poc_stack_benchmark.py tests/contract/test_poc_stack_benchmark.py` GREEN。
- [x] Step 5b-34 **Fallback decision record T110 完成**:
  `specs/001-rag-platform/research.md` の R16 直下に `R16b. Benchmark fallback decision record`
  を追加。T105-T109 の offline benchmark run を evidence として、OpenSearch hybrid search、
  Qdrant vector store、Titan embeddings、Azure/Google/Textract/OSS parser fallback の採用条件を
  benchmark-triggered criteria として明文化。ACL leakage / tenant leakage / deleted document
  reappearance / raw-context logging violation は品質・コスト改善に優先する hard stop とした。
  `tests/contract/test_fallback_decision_record.py` で criteria の存在を固定。検証:
  `PYTHONPATH=src:. python -m unittest tests.contract.test_fallback_decision_record`,
  `PYTHONPATH=src:. python -m ruff check tests/contract/test_fallback_decision_record.py` GREEN。
- [x] Step 5b-35 **Frontend residency fallback T111 完成**:
  `infra/cdk/README.md` に frontend hosting modes を追加し、`frontendHosting=external-vercel` と
  `frontendHosting=aws-nextjs` を明文化。Vercel AI SDK は UI/streaming ergonomics に使えるが、
  strict residency / AWS-only / private-network / customer-managed-key tenant は AWS-hosted Next.js
  fallback を使うルールにした。`apps/web/README.md` を新設し、Next.js web client 側にも
  Vercel-hosted mode と ECS Fargate / CloudFront / WAF / Cognito / KMS / CloudWatch を使う
  AWS-hosted fallback、raw retrieved context を frontend telemetry に出さない原則を記載。
  `tests/contract/test_frontend_residency_fallback.py` で文書化を固定。検証:
  `PYTHONPATH=src:. python -m unittest tests.contract.test_frontend_residency_fallback`,
  `PYTHONPATH=src:. python -m ruff check tests/contract/test_frontend_residency_fallback.py` GREEN。
- [x] Step 5b-36 **lint/format/type/pre-commit T003 完成**:
  `pyproject.toml` の ruff / black / mypy 設定を実行可能な baseline に調整し、mypy は
  stable runtime core / provider config audit / provider policy を対象に固定。`workers` を
  importable package として明示し、`ProviderPolicy.from_mapping` の `fallback_policy` 型を修正。
  `.pre-commit-config.yaml` は ruff / black / secret / large-file / EOF / YAML / mypy hooks を検証済み。
  検証: `python -m black --check . && python -m ruff check . && python -m mypy`,
  `python -m pre_commit validate-config`, `python -m pre_commit run --all-files` GREEN。
- [x] Step 5b-37 **CDK production scaffold T101 完成**:
  `infra/cdk/lib/raku-rag-stack.ts` を placeholder から実 CDK stack に拡張。VPC / KMS /
  S3 document bucket / SQS+DLQ / Secrets Manager / Cognito / Aurora PostgreSQL Serverless v2
  pgvector / ECS Fargate（NestJS API, Python worker, Langfuse）/ CloudWatch dashboard を定義。
  `frontendHosting` context を `external-vercel` / `aws-nextjs` で渡せるようにし、strict residency
  tenant 向け AWS-hosted Next.js fallback service も条件付きで合成。`infra/cdk/README.md` に
  synth/build コマンド、resource scope、ECR image 差し替え前提、pgvector extension 適用を記載。
  `tests/contract/test_cdk_infrastructure.py` で主要 resource tokens と security defaults を固定。
  検証: `cd infra/cdk && npm install && npm run build && npm run synth -- --quiet`,
  `PYTHONPATH=src:. python -m unittest tests.contract.test_cdk_infrastructure -v`,
  `python -m ruff check tests/contract/test_cdk_infrastructure.py`,
  `python -m black --check .`, `python -m ruff check .`, `git diff --check` GREEN。
- [x] Step 5b-38 **Phase 0/1 acceptance checklist non-Docker items 完成**:
  Docker 不要で証跡を取れる受入項目を closing。`scripts/gate.sh all` は Tier A hard gates と
  full suite を通し、472 tests / skipped=3 で GREEN。NestJS facade は `npm run test:api -- --runInBand`
  で 15 suites / 63 tests GREEN、`npm run typecheck --workspaces --if-present` と
  `npm run build:shared` も GREEN。`.github/workflows/ci.yml` は lint → unit → contract →
  integration → security-hard-gate → eval-gate を blocking job として定義し、`.github/workflows/gate.yml`
  は `scripts/gate.sh a` と `scripts/gate.sh all` を push/PR で実行。RT4〜RT18 と deterministic
  mock provider / mock answer / eval smoke の受入チェックを完了へ更新。この時点で残っていた
  Postgres/pgvector migration apply は Step 5b-39 で実 DB により確認。
- [x] Step 5b-39 **Postgres migration + pgvector RT2/RT3 実適用確認**:
  `scripts/postgres-migration-smoke.sh` を追加。既存 Ubuntu Postgres 14 cluster に一時 DB
  `raku_rt_migration_*` を作成し、
  `infra/db/init/01-extensions.sql`、`infra/db/migrations/postgres/0001_core_rls.sql`、
  `infra/db/migrations/postgres/0002_policy_profile_visual_rls.sql` を `psql -v ON_ERROR_STOP=1`
  で実適用。`pg_extension` は `vector:0.8.0` を返し、`tenants` / `documents` / `chunks` /
  `embeddings` / `provider_policies` / `retrieval_profiles` / `logging_policies` の作成を確認。
  `raku_app` role で tenant A は own document を 1 件参照、tenant B は 0 件になる RLS smoke を実行。
  さらに `0002_policy_profile_visual_rls.down.sql` と `0001_core_rls.down.sql` を適用して down path も確認。
  検証: `scripts/postgres-migration-smoke.sh` GREEN（`vector:0.8.0`）。
  Docker は apt で `docker.io` / `docker-compose-v2` を導入し、`dockerd` 手動起動と
  `docker compose -f infra/docker-compose.yml config` は GREEN。ただし
  `docker compose -f infra/docker-compose.yml up -d postgres minio localstack` は image layer 展開時に
  `failed to register layer: unshare: operation not permitted` で停止。これは現在の Docker-in-Docker
  コンテナ権限制約のため、この時点では RT1 を実 Docker host 検証へ回した（Step 5b-43 で完了）。
- [x] Step 5b-40 **RT1 compose trace-sink coverage 強化**:
  RT1 の「trace sink」要件を `docker compose up` のデフォルト依存に含めるため、
  `infra/otel/collector-config.yaml` と `trace-sink` service（OpenTelemetry Collector, OTLP
  :4317/:4318, health :13133）を `infra/docker-compose.yml` と root `docker-compose.yml` に追加。
  Langfuse は引き続き optional observability UI。`scripts/docker-compose-smoke.sh` を追加し、
  Docker Compose v2 config、`up -d --wait postgres minio localstack trace-sink`、pgvector extension、
  LocalStack SQS queue、MinIO readiness、trace sink health を一括検証できるようにした。
  `tests/integration/test_stack_boot.py` も Docker host では MinIO / LocalStack / trace-sink まで検証。
  検証: `docker compose -f infra/docker-compose.yml config`, `docker compose config`,
  `python -m pre_commit run --files infra/docker-compose.yml docker-compose.yml infra/otel/collector-config.yaml scripts/docker-compose-smoke.sh`
  GREEN。現環境では rootful Docker は `unshare: operation not permitted`、rootless Docker は
  `rootlesskit ... /proc/self/exe: operation not permitted`、直接 `unshare` も root/non-root ともに失敗。
  RT1 の最終チェックは privileged Docker host / CI Docker host で `scripts/docker-compose-smoke.sh` 実行待ち。
- [x] Step 5b-41 **RT1 compose smoke を CI blocking job 化**:
  `.github/workflows/gate.yml` に `rt1-compose` job を追加し、GitHub-hosted `ubuntu-latest`
  の Docker host で `docker version` / `docker compose version` を確認してから
  `scripts/docker-compose-smoke.sh` を実行するようにした。これにより Docker が使える CI では
  Postgres+pgvector / MinIO / LocalStack SQS / trace-sink の `docker compose up --wait`
  と各 health smoke が blocking gate になる。workflow 退行は
  `tests/unit/test_ci_eval_gate.py` で `rt1-compose` と smoke script 呼び出しを固定。
  検証: `PYTHONPATH=src python -m unittest tests.unit.test_ci_eval_gate -v` GREEN（2 tests）,
  `python -m pre_commit run --files .github/workflows/gate.yml tests/unit/test_ci_eval_gate.py docs/loop-engineering.md`
  GREEN, `docker compose -f infra/docker-compose.yml config`, `docker compose config`,
  `scripts/gate.sh all` GREEN（476 tests, skipped=6）,
  `python -m black --check . && python -m ruff check . && python -m mypy && git diff --check` GREEN。
  現コンテナでは通常実行の `scripts/docker-compose-smoke.sh` は Docker daemon 未到達で exit 2。
  一時 `dockerd`（vfs / bridge 無し / iptables 無し）では pull 後の image layer 展開で
  `failed to register layer: unshare: operation not permitted`、script 診断も
  `unshare -m failed` を返す。`scripts/docker-compose-smoke.sh` はこの nested-container 不可ケースを
  exit 2（環境不可）へ分類するため、RT1 acceptance は実 Docker host での smoke 実行証跡へ回した
  （Step 5b-43 で完了）。
- [x] Step 5b-42 **RT1 smoke 契約の回帰固定**:
  現コンテナで `dockerd --storage-driver=fuse-overlayfs --bridge=none --iptables=false --ip6tables=false`
  を起動し、`scripts/docker-compose-smoke.sh` を再実行。daemon 起動と pull 開始までは成功したが、
  image layer 展開時に `failed to register layer: unshare: operation not permitted` で停止し、
  script は nested-container 不可として exit 2 を返した。追加で
  `tests/contract/test_rt1_compose_smoke.py` を作成し、RT1 smoke script が
  `postgres` / `minio` / `localstack` / `trace-sink` を `up -d --wait` で起動すること、
  pgvector / SQS queue / MinIO readiness / trace sink health を検査すること、
  Docker 未導入・daemon 未到達・Compose 不在・mount namespace 不可を exit 2 に分類することを固定。
  検証: `PYTHONPATH=src python -m unittest tests.contract.test_rt1_compose_smoke -v` GREEN（3 tests）,
  `bash -n scripts/docker-compose-smoke.sh` GREEN。実 Docker host での smoke 成功は Step 5b-43 で確認。
- [x] Step 5b-43 **RT1 実 Docker host smoke 完了**:
  現コンテナは `CAP_SYS_ADMIN` なし / seccomp 有効で `unshare -m` と rootlesskit が失敗するため、
  RT1 最終検証だけを GitHub-hosted `ubuntu-latest` runner に分離して実行。検証ブランチ
  `codex/rt1-compose-smoke-ci` の Actions run `27870558985` / job `82481643226`
  （RT1 local dependency compose smoke）で `scripts/docker-compose-smoke.sh` が成功し、
  Postgres+pgvector / MinIO / LocalStack SQS / trace-sink は `docker compose up -d --wait` 後に
  Healthy、最終ログは `Docker compose local dependency smoke GREEN`。同 run の Tier A + full suite も
  GREEN。新規ブランチ push の diff 検出だけは Tier B/Tier D で exit 128 になったが、RT1 job の証跡は
  Docker host 上で完了済み。`specs/001-rag-platform/tasks.md` の RT1 acceptance checkbox を完了へ更新。
- [ ] 次: LocalStack/MinIO を使った Tier C 実 integration
- [x] CI: `.github/workflows/gate.yml`（全 push/PR で `gate.sh a`＋`all`＋RT1 compose smoke を実行、PR は §5 分離を CI 強制, T004）— **ループ運用化**。`ci.yml` は 001 本番アダプタ用スケルトンとして温存
- [ ] 各フェーズ末に L3 converge/analyze
- [ ] 安定後（§0 Stage1 昇格条件）に L4 nightly `/schedule`（読み取り専用）

---

## 8. Analyze 由来の整合解決メモ（2026-06-19, `/speckit-analyze`）

`/speckit-analyze` は CRITICAL=0・被覆率100% を確認。検出された整合事項のうち、ループの Tier A 定義と
Track-A 実行に効く 6 件を以下に確定する（これがループの従う正典）。

| # | 解決 | 効果 |
|---|---|---|
| I1 | **API 二系統**: PoC/MVP API = Python `manufacturing/api/*.py`、本番 API = NestJS アダプタ（後続）。001 と同じ二段構え | 実装言語の確定 |
| I2 | **絶対ハードゲート = 6 本**（SC-MFG-006/007/008/009/010/011）。SC-MFG-013/T047（telemetry 正しさ）は **Tier B** | `gate.sh` / Tier A と一致 ✅ |
| I3 | persistence は本番 track。必要時は `src/raku_rag/manufacturing/persistence.py`（plan の `persistence/manufacturing_models.py` は本番アダプタ時に新設） | パス確定 |
| I4 | `010-industry-solution-framework` は **概念マッピングのみ**。002 が semantics を保持し、010 をビルド依存にしない | 依存確定 |
| C1 | ACL/leakage チェックは **US1 から Tier A で毎回**。Phase 8（T053）は最終確認 | 絶対ゲートの早期化 |
| C5 | **Track-A: Phase 2 を stdlib dataclass + in-memory で実装**。T007（SQLAlchemy/Alembic）・Dagster 系（T011a/T031a/T047a/T051a/T071a）は本番アダプタ track へ延期（plan も request path 外と明言） | ゲート 4ms 維持の前提 |

**延期（後続で owner 明確化）**: C2（baseline 採取順）, C3（Base-CR stub と 001 統合の区別表示）, U1（回帰閾値定義）, C4（effective_date edge test）, A1（KPI 名統一）。
