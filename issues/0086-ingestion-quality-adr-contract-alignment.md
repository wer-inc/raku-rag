# 0086 — 取り込み品質ADRと既存parser/visual契約の整合が必要(系統 = architecture / ingestion / safety)

> Priority: **P1 / High** / Status: Open / Labels: `architecture`, `ingestion`, `safety`, `adr`, `rag-quality`

## 背景(なぜ今)

`docs/adr/018-ingestion-parsing-quality-architecture.md` の内容評価中に、ADR が提案する
`ParsedDocument` / quality gate / quarantine / VLM draft 方針と、既存の worker-side parser
provider、visual ingestion、OCR quality metadata、review/document approval 系の実装との重なりが
見つかった。

## どんな課題か

- ADR は `ParsedDocument` をこれから定義する中心契約として扱っているが、`workers/ingest/providers/parsers/__init__.py`
  には既に薄い `ParsedDocument` と provider router が存在する。
- ADR は VLM を「現状 stub」と記述しているが、visual RAG には deterministic VLM、visual chunk、crop/bbox、
  OCR quality metadata、visual evidence promotion gate が既にある。
- ADR の `review_required` / `draft_visual` / quarantine は正しい方向だが、既存の review/approval 状態、
  datasource `approval_policy=review_required`、visual quality metadata と同じ語を使うため、状態意味が衝突しやすい。
- このまま採択すると、別の `ParsedDocument`、別の品質状態、別の review queue を追加してしまい、
  低品質抽出を通常 retrieval から除外する安全境界が複数箇所に分散するリスクがある。

## どこで起きたか

- 画面: `/reviews/documents`、将来の `/reviews` 品質レビュー導線
- API: ingest / search / answer / manufacturing document approval
- コード:
  - `docs/adr/018-ingestion-parsing-quality-architecture.md`
  - `workers/ingest/providers/parsers/__init__.py`
  - `src/raku_rag/workers/ingestion.py`
  - `src/raku_rag/services/visual.py`
  - `src/raku_rag/production.py`
  - `apps/answer-service/server.py`
- 環境: local ADR review
- run id / ingestion id / correlation id: なし
- 再現条件:
  1. ADR-018 を実装計画として読み、既存 parser provider / visual ingestion / review approval 実装と突き合わせる。
  2. `ParsedDocument`、quality status、review routing、provider trace の所有境界を確認する。

## 影響

- 営業デモへの影響: 「低品質抽出は通常回答に混ぜない」と説明しても、実装境界が分散すると根拠を示しにくい。
- 本番クライアントへの影響: 低品質 OCR、表崩れ、VLM draft、未承認視覚解釈がどの層で除外されるか曖昧になる。
- セキュリティ/安全: high-risk answer の approved/effective citation gate の前段で、quality gate が確実に retrieval filter へ伝播しない可能性がある。
- データ品質: provider/version/schema が二系統になると reindex/backfill/regression 比較が難しくなる。
- UX: review queue に「承認待ち文書」と「抽出品質要確認block/page」が混在し、reviewer の判断軸が曖昧になる。

## どう解決すべきか

1. 実装方針:
   - 既存 `workers/ingest/providers/parsers.ParsedDocument` を廃止/拡張/移管する方針をADRに明記する。
   - `ParsedDocument v1` の最小契約を、既存 `VisualAsset` / `LayoutRegion` / `Chunk.metadata` / ingestion run projection と接続する。
   - quality status と manufacturing approval status を別軸として命名し、retrieval filter の強制層を1つに決める。
   - `review_required` / `draft_visual` は index投入可否と high-risk citation eligibility を機械判定できる metadata として保存する。
2. UI/UX 方針:
   - document approval review と extraction quality review を同じ画面に出す場合でも、状態ラベルと操作を分ける。
   - page/block単位の品質理由、provider trace、crop/bbox、再処理アクションを reviewer に表示する。
3. テスト方針:
   - low OCR confidence / mojibake / VLM-only / missing bbox の chunk が search/answer/high-risk citation に出ないことを固定する。
   - 既存 visual ACL/deletion hard gate と quality filter が同時に効くことを確認する。
   - provider policy により Azure/Google/Docling 等へ raw bytes が出る前に opt-in が強制されることを確認する。
4. 移行や運用上の注意:
   - 既存 indexed chunks に quality status がない場合の reprocess/reindex 方針をADRに入れる。
   - Golden Eval Pack は実データ由来の private corpus を扱うため、PII/秘密情報を含めない運用を決める。

## QA checklist

- [ ] 再現テストがある。
- [ ] 正常系が確認できる。
- [ ] 失敗時の表示/応答が確認できる。
- [ ] tenant/ACL 境界を越えない。
- [ ] security/safety gate を弱めていない。
- [ ] Playwright または API smoke で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 受け入れ条件(DoD)

- ADR が既存 parser provider / visual ingestion / approval review の所有境界を正確に記述している。
- `ParsedDocument v1`、quality status、review routing、retrieval eligibility のSSOTが決まっている。
- low-quality / draft visual / missing-anchor evidence が通常 retrieval と high-risk citation から除外されるテストがある。
- 既存の ACL、tenant isolation、tombstone、audit、no-train/provider policy を弱めていない。

## スコープ外

- Docling / cloud OCR / VLM の即時本番有効化。
- 顧客データを使った live provider 評価。
- safety/approval/retrieval filter を bypass する demo-only flag。

## 参照

- `docs/adr/018-ingestion-parsing-quality-architecture.md`
- `workers/ingest/providers/parsers/__init__.py`
- `src/raku_rag/workers/ingestion.py`
- `src/raku_rag/services/visual.py`
- `specs/021-visual-pdf-understanding-prod/plan.md`
- `issues/0070-source-level-document-review-drilldown-and-bulk-approval.md`
- `issues/0071-document-review-indexing-status-gate.md`
