# 0021 — 根拠文書レビューの旧版化が不可逆に見えず、誤操作 recovery 方針も未定(系統 = approval / document-review / ux)

> Priority: **P2 / Medium** / Status: Open / Labels: `approval`, `document-review`, `ux`, `safety`, `audit`

## 背景(なぜ今)

ユーザー確認で、データソース同期後に `review_required` 文書が根拠文書レビューへ入り、そこで表示される
「旧版化」「承認済み」が何を意味するか分かりにくいことが判明した。さらに「操作ミスで旧版化にした場合、
どう recovery するのか」が未定であることも確認された。

文書承認ワークフローは `draft → pending_review → approved → obsolete` の前進専用で、
通常の `transition` では `obsolete → approved` に戻せない。つまり UI 上の軽い操作に見える一方で、
実体は正式根拠から外す不可逆に近い安全操作になっている。

## どんな課題か

- `根拠文書レビュー` 画面で `旧版化` ボタンがワンクリック実行でき、不可逆性や影響が十分に伝わらない。
- `旧版化` は状態名ではなく操作名だが、ユーザーには「単なるラベル変更」に見え得る。
- `obsolete` 後の通常 recovery 経路が UI/運用として定義されていない。
- 実装上は前進専用のため、誤って `obsolete` にした文書を通常承認フローで `approved` に戻せない。
- 例外的な `import_external` は source-of-truth 取り込み用であり、Undo UX として扱うには監査・発効日・
  `obsolete_at`/`superseded_by` クリア方針が未整理。

期待挙動:

- `obsolete` 相当の操作は、ユーザーに「正式根拠から外す不可逆/準不可逆操作」と分かる。
- 誤操作時の回復方法が UI と運用で明示されている。
- 誤操作を防ぐ確認、理由、必要なら差し替え先文書 ID が記録される。

実際の挙動:

- `旧版化` ボタンを押すと `transition(doc, "obsolete")` が即実行される。
- 確認ダイアログ、理由入力、差し替え先文書 ID、Undo/復旧導線が無い。

## どこで起きたか

- 画面: `/reviews/documents` の `根拠文書レビュー`
- 画面: `/reviews/:artifactId` 内の埋め込み `根拠文書レビュー` ミニフォーム
- API: `POST /v1/manufacturing/documents/:documentId/approval`
- コード: `apps/web/app/components/FullSaasScreen.tsx` `DocumentApprovalQueueBody`
- コード: `apps/web/app/components/FullSaasScreen.tsx` `ReviewDetailBody`
- コード: `src/raku_rag/manufacturing/ingestion/approval.py`
- 環境: local UI review
- run id / ingestion id / correlation id: なし
- 再現条件:
  1. `review_required` のデータソースを同期し、文書を `pending_review` として取り込む。
  2. `/reviews/documents` で対象文書の `旧版化` を押す。
  3. 文書状態が `obsolete` になる。
  4. 通常 UI から `approved` に戻す導線が無い。

## 影響

- 営業デモへの影響: レビュー操作の意味が伝わらず、誤操作時に復旧できない印象を与える。
- 本番クライアントへの影響: 正式根拠に使うべき文書を誤って `obsolete` にし、高リスク回答が
  `approved_citation_missing` で止まる、またはナレッジ品質が低下する。
- セキュリティ/安全: draft/obsolete を一次根拠にしない安全ルール自体は正しいが、誤った obsolete 化で
  安全ゲートが必要以上にブロックする運用事故が起き得る。
- 監査: 誰が・なぜ旧版化したか、誤操作だった場合にどう復旧したかを追跡しにくい。
- UX: `旧版化` が「廃止」「正式根拠から外す」「戻せない可能性がある」操作だと分からない。

## どう解決すべきか

1. **文言/情報設計**
   - ボタン文言を `旧版化` から `旧版にする` または `正式根拠から外す` に変更する。
   - 状態ラベルは `旧版` / `廃止済み` のどちらを採用するか決め、操作名と状態名を分離する。
   - `obsolete` の説明を「高リスク回答の正式根拠には使われない。参照時は警告扱い」と明示する。
2. **誤操作防止**
   - `obsolete` 遷移には確認ダイアログを必須にする。
   - 理由入力を必須化する。
   - 可能なら差し替え先文書 ID (`superseded_by`) を入力できるようにする。
   - POST 中は二重送信を防止する。
3. **recovery 方針**
   - Option A: `obsolete` は通常 UI では戻せないと明示し、誤操作時は再同期/再取込して新しい文書 ID を承認する運用にする。
   - Option B: 管理者専用の audited restore/reinstate 操作を設計する。実施時は理由、承認者、新しい `effective_date`、
     `obsolete_at`/`superseded_by` の扱いを必須にする。
   - Option C: 上流 DMS/QMS の `import_external` を唯一の復旧経路にする。ただし [0017](0017-safety-gate-evidence-validity.md)
     の obsolete 復活リスクを先に解消する。
4. **テスト方針**
   - UI: obsolete 操作に確認なしで POST しないこと。
   - UI: 理由未入力では実行できないこと。
   - API/domain: 通常 workflow は `obsolete → approved` を引き続き禁止すること。
   - Audit: obsolete と restore/reimport の理由・actor・対象 document_id が残ること。

## QA checklist

- [ ] `旧版にする` / `正式根拠から外す` の文言がユーザーに意味を伝える。
- [ ] `obsolete` 操作は確認後にのみ実行される。
- [ ] 理由未入力では `obsolete` にできない。
- [ ] 二重クリックで重複 POST されない。
- [ ] 誤操作時の回復方針が UI または runbook に表示される。
- [ ] `obsolete` 文書は高リスク回答の approved+effective 根拠にならない。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。

## 受け入れ条件(DoD)

- `obsolete` 操作の不可逆性/影響が UI 上で明確になっている。
- 確認、理由、必要なら差し替え先文書 ID が監査可能な形で保存される。
- 誤操作時の recovery 方針が Option A/B/C のいずれかで決定され、UI または運用文書に反映されている。
- 通常 workflow の前進専用ルールと safety gate を弱めていない。
- 回帰テストが追加されている。

## スコープ外

- フル DMS、電子署名、任意バージョン rollback の一般提供。
- safety gate を緩めて obsolete 文書を正式根拠に戻すこと。
- audit を残さない手動 DB 修正。

## 参照

- `apps/web/app/components/FullSaasScreen.tsx` `DocumentApprovalQueueBody`
- `apps/web/app/components/FullSaasScreen.tsx` `ReviewDetailBody`
- `src/raku_rag/manufacturing/ingestion/approval.py`
- `specs/002-manufacturing-field-knowledge-rag/data-model.md`
- [0015-review-detail-ux-state-machine-mismatch.md](0015-review-detail-ux-state-machine-mismatch.md)
- [0017-safety-gate-evidence-validity.md](0017-safety-gate-evidence-validity.md)
