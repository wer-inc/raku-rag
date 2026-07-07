# 0087 — ADR-018 実装ステータスの残差ギャップ確認(系統 = architecture / ingestion / rag-quality)

> Priority: **P1/High** / Status: Resolved / Labels: `architecture`, `ingestion`, `rag-quality`, `adr-018`

## 背景(なぜ今)

`docs/adr/018-ingestion-parsing-quality-architecture.md` が develop に取り込まれた後、ADR の内容が漏れなく実装済みかを確認した。
ADR 付録は「コードは完了、残りは外部リソースでの live 検証と限定事項のみ」と記述しているが、本文の要求と実装形の間に
まだ説明・テスト・実装の差分が残っている。

## どんな課題か

- ADR は §9.1 / Phase B で PDF / DOCX / PPTX / 画像系文書を Docling-first としているが、
  実装の `build_structured_parser()` は `TextStructuredParser`、`DocxStructuredParser`、
  `SpreadsheetStructuredParser` を先に評価し、Docling は PDF / PPTX / image などのフォールスルーとして使われる。
  DOCX は実質 Docling-first ではない。
- ADR は `review_required` / `draft_visual` を「通常 index に入れず quarantine store へ」と書くが、
  実装は同じ chunk/vector store に保存し、`RetrievalService` と high-risk citation gate で除外する論理 quarantine になっている。
  安全上は retrieval filter が効くが、ADR の物理/論理 quarantine の意味が未確定。
- `DoclingStructuredParser._format_options()` は Docling の built-in OCR を無効化しようとするが、
  API drift 時に `None` を返して `DocumentConverter()` default にフォールバックする。Docling default が OCR を有効化する場合、
  §4.2「OCR は Docling 内蔵ではなく独立 provider」の fail-closed 要件とズレる可能性がある。
- ADR 自身の付録にも未完として、実顧客文書での閾値確定、クラウド OCR/VLM の本番 credential 付き live 検証、
  tenant ごとの cloud egress policy、reviewer UI への block 単位 provider 詳細投影が残っている。

## どこで起きたか

- 画面: `/reviews/extraction`
- API: `/internal/reviews/extraction`, `/internal/reviews/extraction/actions`, ingestion worker
- コード:
  - `docs/adr/018-ingestion-parsing-quality-architecture.md`
  - `src/raku_rag/services/structured_ingestion.py`
  - `src/raku_rag/providers/structured_parsers.py`
  - `src/raku_rag/providers/docling_parser.py`
  - `src/raku_rag/services/retrieval.py`
  - `src/raku_rag/persistence/postgres.py`
- 環境: develop (`651a1b6 Merge pull request #99 from wer-inc/018-ingestion-quality-architecture`)
- run id / ingestion id / correlation id: なし
- 再現条件:
  1. ADR §9.1 / Phase B の Docling-first 方針と `build_structured_parser()` の parser order を比較する。
  2. ADR §8.5 の quarantine store 方針と `StructuredIngestionService._store.upsert(...)` / retrieval quality filter を比較する。
  3. `DoclingStructuredParser._format_options()` の fallback を確認する。

## 影響

- 営業デモへの影響: 「ADR は完全実装済み」と説明すると、Docling-first や quarantine の意味を突っ込まれたときに齟齬が出る。
- 本番クライアントへの影響: DOCX/HTML の構造化品質改善が Docling 経由でない可能性を期待値として説明する必要がある。
- セキュリティ/安全: retrieval/high-risk gate は効いているが、物理 quarantine でないため、別経路が store を直接読む場合は同じ品質 filter が必要。
- データ品質: Docling built-in OCR fallback が fail-open になると OCR provider provenance が曖昧になる。
- UX: reviewer UI に block 単位 provider/version/config が出ないため、難物レビューの説明性が一部不足する。

## どう解決すべきか

1. 実装方針。
   - ADR を「Docling-first for PDF/PPTX/image, existing parser first for text/DOCX/CSV/XLSX/HTML」へ修正するか、
     実装を ADR 通り DOCX も Docling-first に変更する。
   - quarantine を物理 store として分離するのか、論理 quarantine として正式化するのかを ADR に明記する。
   - Docling built-in OCR 無効化に失敗した場合は default converter に戻さず `review_required` / provider_error に落とす fail-closed 方針を検討する。
2. UI/UX 方針。
   - reviewer UI に provider/model/version/config_hash/prompt_version の詳細表示を追加するか、ADR の範囲外として明記する。
3. テスト方針。
   - DOCX が Docling-first か existing-parser-first かを固定する contract test を追加する。
   - quarantine が物理/論理のどちらかを示す regression test を追加する。
   - `_format_options()` 失敗時に Docling OCR default へ silent fallback しないことをテストする。
4. 移行や運用上の注意。
   - 既存 indexed chunk は logical quarantine 前提なので、直接 store を読む管理 API / export / metrics は quality filter を明示的に通す。

## QA checklist

- [x] 再現テストがある。
- [x] 正常系が確認できる。
- [x] 失敗時の表示/応答が確認できる。
- [x] tenant/ACL 境界を越えない。
- [x] security/safety gate を弱めていない。
- [x] API smoke / web typecheck で確認できる。
- [ ] AWS stg/live smoke が必要な場合は correlation id を保存する。

## 対応状況 (2026-07-07)

- Docling-first: `build_structured_parser()` を Docling -> text -> spreadsheet -> docx の順にし、DOCX が Docling-first になる contract test を追加。
- Quarantine: in-memory/Postgres の物理 quarantine store を追加し、ingestion / structured ingestion / visual worker / reindex / deletion / Dagster publish を primary/quarantine 分離に変更。review approve は quarantine から primary へ昇格する。
- Docling OCR: OCR 無効化設定に失敗した場合、default `DocumentConverter()` へ戻さず fail-closed で `review_required` / provider_error に落とす。
- Tenant egress: production structured ingestion では `PostgresProviderPolicyRepository` を Docling parser に渡し、cloud OCR/VLM/vision detector 呼び出し直前に tenant provider policy を評価する。`RAKU_ALLOW_CLOUD_EGRESS` は environment backstop として残す。
- Reviewer UI: review queue item に `provider_details` / `block_provider_details` を追加し、web `/reviews/extraction` に provider/version/model/config/prompt context を表示する。
- ADR: 付録の既知限定事項を更新し、コード上の残差は解消済み、残るのは実顧客文書の閾値確定と本番資格情報つき live provider 検証のみと明記。

検証:

- `PYTHONPATH=src python3 -m unittest tests.contract.test_provider_policies tests.integration.test_structured_ingestion tests.unit.test_docling_parser -v`
- `PYTHONPATH=src python3 -m unittest tests.integration.test_reviews_endpoint tests.integration.test_ingestion_quality_gate tests.integration.test_reindex tests.unit.test_review_actions tests.unit.test_visual_provider_profile tests.integration.test_ingest_queue tests.postgres.test_visual_realpg_security -v`
- `npm run typecheck --workspace @raku-rag/web`
- `scripts/gate.sh a`
- `scripts/gate.sh separation`
- `scripts/gate.sh all` (GREEN, 1948 tests, skipped=6)

## 受け入れ条件(DoD)

- ADR 018 の「実装済み」表現が実コードの routing/quarantine/egress/provider provenance と一致している。
- Docling-first の対象形式がコードと ADR の両方で固定されている。
- quarantine の物理/論理境界が明文化され、direct store read 経路にも品質 filter の責務がある。
- Docling OCR 無効化が fail-closed で保証される、または ADR が fallback 挙動を明示している。
- 既存の ACL、tenant isolation、tombstone、high-risk evidence gate を弱めていない。

## スコープ外

- 顧客実データを使った無承認の live provider 評価。
- cloud OCR / VLM の強制有効化。
- retrieval/high-risk filter を緩める demo-only flag。

## 参照

- `docs/adr/018-ingestion-parsing-quality-architecture.md`
- `src/raku_rag/services/structured_ingestion.py`
- `src/raku_rag/providers/structured_parsers.py`
- `src/raku_rag/providers/docling_parser.py`
- `src/raku_rag/services/ingestion_quality.py`
- `src/raku_rag/services/retrieval.py`
- `issues/0086-ingestion-quality-adr-contract-alignment.md`
