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

- **(a) 保護パス**: `tests/security/**`, `tests/manufacturing/test_*gate*.py`, `scripts/gate.sh`
  → pre-commit/CI が「保護テスト + `src/` を同一コミットで変更」を弾く（`scripts/gate.sh separation`）。
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
- [ ] 残: T066 PoC v0 縦串(end-to-end) / Polish（T067 quickstart検証 / T069 unit / T070 security review、T068 docs・T072 UI・T071a Dagsterは本番/UI track）
- [x] CI: `.github/workflows/gate.yml`（全 push/PR で `gate.sh a`＋`all` を実行、PR は §5 分離を CI 強制, T004）— **ループ運用化**。`ci.yml` は 001 本番アダプタ用スケルトンとして温存
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
