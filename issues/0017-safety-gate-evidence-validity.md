# 0017 — 安全ゲートが「誤った承認状態の証拠」を使い得る(失効/復活/自己申告/stale)(系統 = gate)

> Priority: **P1 / High** / Status: Open / Labels: `safety`, `manufacturing`, `safety-gate`, `correctness`, `SC-MFG-005/006`

## 背景(なぜ今)

安全ゲートの**判定ロジック自体**(高リスク ∧ approved+effective 無し ⇒ 断定不可)は堅牢
(`safety/gate.py:173-180`)。問題はその手前、「ある引用が *本当に* approved かつ発効中かつ失効していない」を
判定する**証拠の妥当性**側に 4 つの穴があること。どれも「高リスク回答が、実際には正式根拠でない証拠を
根拠に断定してしまう」= SC-MFG-005/006 の核心に触れる。

## 現状(根拠 / 4 サブ課題)

### A. 失効(expiry)が未実装 — 上限チェックが無い
- `is_effective`(`safety/gate.py:49-61`)は `eff <= today` の**下限のみ**。上限(失効)を見ない。
- `ManufacturingDocumentMetadata`(`domain/metadata.py:78-85`)に `valid_until`/expiry フィールドが**無い**。
  しかも metadata のコメントは「valid = not future, **not expired**」と書いており実装と矛盾。
- data-model は「発効日は未来でも**失効でもない**ことが有効条件」と規定(`data-model.md:120-121`)。
- 結果:発効済みなら**何年前に失効していても** approved+effective とみなされ、高リスク回答の正式根拠になる。
  失効は手動 `obsolete` 遷移でしか表現できない。

### B. `import_external` が obsolete を復活させ得る
- `ingestion/approval.py:119-141`。`approval_status` を**省略すると APPROVED に既定**
  (`:128` `external.get("approval_status", ApprovalStatus.APPROVED.value)`)。
- 設計上(FR-MFG-004a)`_assert_legal_transition` を**意図的にバイパス**(source-of-truth 上書き)。
  → 空/部分ボディの import が **OBSOLETE 文書を approved に復活**させ、古い `effective_date` を保持、
  `obsolete_at`/`superseded_by` も消さない。
- 露出経路:`apps/answer-service/server.py:1896-1903` → `manufacturing.controller.ts:186-198`。

### C. 呼び出し側の自己申告で「承認済み」扱い(ドラフト生成)
- `DraftGenerator._has_approved_effective_evidence`(`drafts/generator.py:180-202`)は、引用の `document_id` が
  `manufacturing_filters["approved_source_document_ids"]` に含まれると、**`get_mfg_meta`/`is_approved_effective`
  を見る前に `return True`**(`:194-197`)。
- この `manufacturing_filters` はリクエストボディ由来(`server.py:2001`)。→ 呼び出し側が任意の文書を
  「承認済み」と自己申告でき、安全項目が `confirmed` でレンダリングされる。
- ※ ドラフトは status=draft で人手レビュー必須なので即時の対外影響は限定的だが、**レビューアを
  「確認済み」表示で誤誘導**し得る(誤承認の入口)。

### D. 承認メタデータのプロセス内キャッシュが stale
- `get_mfg_meta`(`app.py:287-289`)は `self._mfg_meta` のキャッシュを **TTL/無効化なし**で返す。
- コネクタ同期/取り込み経路は `ProductionSystem.attach_manufacturing_metadata` で `Document.metadata`+registry を
  更新するが**このキャッシュを触らない**(`production.py:340-370`)。
- → プロセス外で `obsolete` 化/承認変更が起きても、高リスクゲートが**古い承認状態を読む**(obsolete を
  approved と誤認し得る)。

## 影響

A〜D いずれも「高リスク回答が、失効/旧版/未承認/自己申告の証拠を *approved+effective* と誤判定して断定する」
方向の安全性低下。安全ゲートの存在意義(SC-MFG-005/006)を侵食する。

## 提案作業(何をどう対応)

- **A:** `ManufacturingDocumentMetadata` に `valid_until`(または発効日+有効期間)を追加し、`is_effective` を
  `eff <= today < valid_until` に拡張。expiry 不明時は**未来日付と同じく invalid に fail-safe**。
  あるいは「失効は obsolete 遷移でのみ運用」と設計を確定し、metadata の誤コメントを削除(=実装と spec の一致)。
- **B:** `import_external` で `approval_status` を**必須化(省略は raise)**。OBSOLETE からの復活時は
  **新しい `effective_date` を必須**にし `obsolete_at`/`superseded_by` をクリア。`import_external` を
  より高権限ロールに限定。監査は既に出る(`approval.py:138-141`)。
- **C:** `approved_source_document_ids` ショートサーキットを**撤去**(または advisory 扱いにして
  最終判定は必ずサーバ側 `get_mfg_meta`+`is_approved_effective` で行う)。`generator.py:194-197` を修正。
- **D:** 承認状態の長寿命プロセス内キャッシュを**廃止**(リクエスト毎に `Document.metadata` を読む。cache-miss 経路は
  既にそれをしている)か、`attach_manufacturing_metadata` 側から**明示的に invalidate**(または version 付き)。

## 受け入れ条件(DoD)

- [ ] 失効済み approved 文書が高リスク回答の approved+effective 根拠にならない(回帰テスト)。
- [ ] 空/部分ボディの `import_external` が obsolete を approved に復活させない(必須化 or 明示発効日)。
- [ ] `approved_source_document_ids` の自己申告だけでは安全項目が `confirmed` にならない。
- [ ] プロセス外の obsolete 化が高リスクゲートに即時反映される(stale を読まない)。

## スコープ外

- 安全ゲートの判定式自体(変更不要)。承認 UI は [0015](0015-review-detail-ux-state-machine-mismatch.md)。

## 参照

- `src/raku_rag/manufacturing/safety/gate.py:49-61,64-72,173-180`, `src/raku_rag/manufacturing/domain/metadata.py:78-85`
- `src/raku_rag/manufacturing/ingestion/approval.py:119-141`, `src/raku_rag/manufacturing/drafts/generator.py:180-202`
- `src/raku_rag/manufacturing/app.py:287-289`, `src/raku_rag/production.py:340-370`
- `specs/002-manufacturing-field-knowledge-rag/data-model.md:120-121`, spec FR-MFG-004a/005/006
