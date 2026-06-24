# MVP実演フロー エビデンス・パス (2026-06-24)

goal.md の MVP Completion Sprint 着手前に、10ステップ縦切りを**ライブ実走**して「どこで折れるか」を
証拠化した記録。スタック: web:3002 → API:3000 (`/v1/manufacturing/*`) → answer-service:8088 →
Postgres `raku_demo`（curated 18文書）。認証: `Authorization: Bearer <任意>` + HMAC `X-User-Token`
(dev-token issuer; alice=tenant_admin+reviewer, bob=field_user)。

## 10ステップ スコアカード

| # | ステップ | 結果 | 証拠 |
|---|---|---|---|
| 1 | 管理者がPDF/Excelをアップロード | ⚠️ 未UI実走 | `/manufacturing/sources/:id/sync`・`/internal/ingest` 実在、seedで18文書取込済 |
| 2 | 取込完了 | ✅ | 18文書 non-tombstone、`ingestion-runs/:id` 実在 |
| 3 | 文書承認キューで approved | ✅(API) / ⚠️(画面) | `documents/:id/approval` で transition 成功。状態内訳: approved15/obsolete1/draft1/pending_review1。**専用の承認キュー画面は未**（`apps/web` は `reviews` のみ） |
| 4 | 現場ユーザーが質問 | ✅ | `POST /manufacturing/answer` status=ok |
| 5 | 根拠付き回答 | ✅ | クエリA=4引用、grounded text あり |
| 6 | 引用元を確認 | ✅(データ) | citation に `approval_status=approved` / `effective_date` / `approval_source` / `chunk_id`。`documents/:id/citation-view` 実在 |
| 7 | 危険作業質問は保留 | ✅ | V-205: `high_risk=true` + `requires_onsite_confirmation` + notice。ESD(レビュー中文書): `insufficient_evidence`（承認証拠なしで断定せず） |
| 8 | 点検チェックリスト draft 生成 | ✅ | `kind="checklist"` で `art_1` 生成、status=`draft` |
| 9 | reviewer 承認/却下 | ✅ | assign[200] → review → `approved`。**生成直後は draft＝自動承認されない（ハードゲート成立）** |
| 10 | 監査+ダッシュボード反映 | ✅一部 / ❌一部 | dashboard・kpi・safety-telemetry は200で本物のKPIを返す。**`governance/status` と `policy/data-use` は500**（下記B1） |

## ハードゲート (横断UAT)

| ID | 項目 | 結果 | 証拠 |
|---|---|---|---|
| X-01 | 他テナント非可視 | ✅ live + unit | bob(manuals権限なし)で同クエリ→`insufficient_evidence`・0引用。`test_tenant_isolation.py`(6 cases) |
| X-02 | ACL外がrerank/LLMに入らない | ✅ live + unit | 同上(pre-filter)。`test_acl_leak.py`・`test_case5_prefilter_boundary_not_postfilter` |
| X-03 | tombstone再検索されない | ✅ unit | `test_deletion_reappearance.py` |
| X-04 | no-train default | ⚠️ | コード側 fail-safe は green だが、**ライブ可視化(policy/data-use)はB1で死亡**、データseedも0行 |
| X-05 | raw retrieved context 非保存 | ✅ unit | `test_logging_policy.py::test_raw_retrieved_context_is_disabled_by_default` |

（gate.sh all: 857テスト green。唯一の失敗は `test_stack_boot`＝このサンドボックスでコンテナ起動不可の環境制約で、コードと無関係。）

## 確定したパンチリスト

### B1 [HIGH／バグ] governance/no-train パネルがライブで500
- 症状: `GET /v1/manufacturing/governance/status` と `policy/data-use` が502 (内側 answer-service 500)。
- 真因: `manufacturing_data_use_policies` テーブルが **`raku` スキーマに作られ `public` に無い**（`to_regclass('public.…')`=null）。answer-service の接続 search_path で解決できず `relation does not exist`。加えて **行数0**（seed無し）。
- 影響: step-10 のガバナンス表示が欠落。**PoCの“売り”である no-train / データ所在地 / 保持期間（DEMO.md §8）の実演が不可**。
- 直し: マイグレーションを public（サービスの search_path）に揃える＋デモseedで1行投入。小さい・高レバレッジ。

### B2 [MED／UX] 文書承認キューの専用画面が無い
- `documents/:id/approval` のAPIはあるが、`apps/web` に承認キュー画面が無く `reviews`(AIドラフト)と混在。goal.md P0-2 の核。

### B3 [MED／UX] ロール別ナビ未強制
- dev発行のroleはあるが、画面/ナビのrole gatingが弱い（goal.md P0-3）。

### B4 [LOW] 軽微
- draft生成レスポンスの `draft_type` が null で返る（機能は正常）。`answer` の `text` が `display_sections` と二重で、UIが拾う形か要確認。

## 結論（着手順の根拠）
コア（回答・高リスクゲート・引用メタ・ACL・未承認は断定せず・ドラフト承認ワークフロー・KPI）は**ライブで動く**。
不足は「機能」ではなく (a) ガバナンス・パネルの実バグ B1、(b) 2枚の業務画面 B2/B3。
→ **B1 を最初に潰す**（小さく、売りに直結、step-10とX-04の可視面を復旧）。次に B2（文書承認キュー画面）→ B3（ロール別ナビ）。
Citation Viewer は「新規」ではなくデータが揃っているので「完結条件の仕上げ」。
