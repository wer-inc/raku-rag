# 0020 — 画像/PDF混在時に短い汎用質問だけでは対象PDFが上位に来ない(系統 = retrieval / visual-pdf)

> Priority: **P1 / High** / Status: Open / Labels: `retrieval`, `visual-rag`, `pdf`, `ux`, `production-smoke`, `ranking`

## 背景(なぜ今)

`RAKU_VISUAL_EVIDENCE_PROMOTION=true` を有効化した AWS stg live 検証で、画像/PDF の visual evidence promotion 自体は成立した。
画像は自然質問で `visual_evidence_verified=true` の citation 付き回答まで確認済み。
PDF も文書タイトルや文書名を質問に含めた場合は、page aggregate citation 付きで回答できた。

一方、同じコレクションに類似した画像/PDF/手順書が複数ある状態で、短い汎用質問だけを投げると、直近アップロードした対象PDFではなく既存の類似画像文書が検索上位に来るケースを確認した。
これは verifier / safety gate / promotion の失敗ではなく、retrieval / ranking / target selection UX の課題として扱う。

## どんな課題か

- ユーザーが `How do I stop the pump safely?` のような短い汎用質問をした場合、対象文書を明示しない限り、似た内容の別文書が上位候補になることがある。
- PDF そのものは取り込み済みで、文書名・タイトル・アンカーを含む質問では回答できるため、問題は PDF parsing ではなく検索候補の選ばれ方にある。
- `manufacturing_filters` が回答パス上で retrieval 後に効く箇所があり、対象文書が初期 top-k に入らない場合、後段フィルタだけでは救えない。
- visual/OCR 由来の回答文が、ヘッダー行や重複行を含んで読みにくくなるケースがある。これは本 issue の副次課題として扱う。

## どこで起きたか

AWS stg live 検証、2026-06-28。

- Deploy SHA: `c48e602`
- Runtime: `RAKU_VISUAL_EVIDENCE_PROMOTION=true`
- Verifier quorum: 2
- Image smoke:
  - Run key: `visprom-20260628074457-7708ca`
  - Ingestion: `ing_508e7d4519139a54a5f3`
  - Result: `status=ok`, `visual_evidence_verified=true`
  - Citation: page aggregate visual chunk
  - Correlation: `trace_c9d2ab76a885`
- PDF smoke:
  - Run key: `vispdf-20260628074609-c3f10d`
  - Ingestion: `ing_5e5ff9b4175c72e1e6fd`
  - Generic short query: target PDF が上位候補に入らないケースあり
  - PDF-specific query: `APPROVED PDF WORK INSTRUCTION: what should I press to stop the pump safely?`
  - Result: `status=ok`, `visual_evidence_verified=true`
  - Correlation: `trace_82f4cb7e1e7f`
  - PDF title query: `Pump Stop PDF Instruction: what should I press to stop the pump safely?`
  - Result: `status=ok`, `visual_evidence_verified=true`
  - Correlation: `trace_f8c4b05895ba`

関連コード候補:

- `src/raku_rag/services/retrieval.py`
- `src/raku_rag/services/answer.py`
- `src/raku_rag/manufacturing/api/answer_ext.py`
- `src/raku_rag/services/visual.py`
- `src/raku_rag/workers/ingestion.py`
- `apps/web/` の質問UI、ソース/文書選択UI

## 影響

- 営業デモや実運用で、ユーザーが直近アップロードした PDF について聞いたつもりでも、別の類似文書を根拠に回答される、または根拠不足に見える可能性がある。
- 「画像/PDF対応はできているのか」という評価が、retrieval UX の不足によって不安定に見える。
- 本番クライアントの文書数が増えるほど、短い質問だけで対象文書を一意に当てることは難しくなる。

## どう解決すべきか

1. **対象文書/ソースを検索前に絞れる retrieval path を作る**
   - `document_id`, `source_id`, `equipment_id`, `content_type`, `modality` などの filter を retrieval 前または候補拡張時に反映する。
   - retrieval 後フィルタだけでなく、vector store / metadata search の候補生成段階で target-aware にする。
   - すぐに完全な metadata pre-filter が難しい場合は、filtered query では candidate pool を広げてから server-side filter を適用する。

2. **UI に対象選択を入れる**
   - 質問画面で「全ドキュメント」「このソース」「この文書」などを選べるようにする。
   - ソース詳細/取込結果から質問に遷移した場合は、その source/document を初期選択する。
   - filter chip を表示し、ユーザーが今どの範囲に質問しているか分かるようにする。

3. **ranking / boosting を追加する**
   - 文書名、タイトル、設備ID、ソース名、直近アップロード文書などの exact / near-exact match を boost する。
   - visual page aggregate chunk を、行単位OCR chunkよりも citation 用候補として優先できるようにする。

4. **回答表示を整える**
   - OCR由来の重複行、ページヘッダー、ファイル名だけの行を primary answer から抑制する。
   - citation/audit には元テキストを保持し、表示だけを読みやすくする。

5. **説明可能な no-answer を返す**
   - 対象文書が検索候補に入らない場合は、単なる根拠不足ではなく「対象文書を指定してください」「検索範囲を広げてください」などの UI action を出す。

## QA checklist

- [ ] 同一テナントに、類似した pump stop 手順の PNG、PDF、無関係マニュアルを投入する。
- [ ] 汎用質問 `How do I stop the pump safely?` で、最も妥当な文書が選ばれるか、または UI 上で対象文書を選ぶ導線が出る。
- [ ] PDF の `document_id` / `source_id` filter 付き質問で、対象PDFが retrieval candidates に含まれる。
- [ ] PDF target query が `status=ok`、`visual_evidence_verified=true`、page aggregate citation 付きで返る。
- [ ] 画像 target query も同じ条件で regression しない。
- [ ] unauthorized document を filter に指定しても、検索結果・回答・citation・asset が漏れない。
- [ ] draft / obsolete / unverified visual evidence は、引き続き high-risk safety gate で回答抑止される。
- [ ] Playwright で質問画面の source/document selector、filter chip、no-answer action が確認できる。
- [ ] AWS stg で PNG/PDF upload、ingestion completion、generic query、target-filtered query、negative ACL query の live smoke を行い、correlation id を保存する。

## 受け入れ条件(DoD)

- `RAKU_VISUAL_EVIDENCE_PROMOTION=true` の AWS stg で、画像/PDF の target-filtered 質問がどちらも verified citation 付きで成功する。
- 短い汎用質問で対象が曖昧な場合、ユーザーが次に何をすべきか分かる UI/応答になる。
- retrieval の server-side filter が tenant/ACL 境界を越えない。
- visual verifier quorum、安全ゲート、ACL、draft/obsolete ルールを弱めずに通る。
- regression test と Playwright smoke が追加される。

## スコープ外

- verifier quorum を下げて通すこと。
- 営業デモ専用の bypass flag を追加すること。
- ACL や high-risk safety gate を frontend 側だけで制御すること。
- PDF parsing や OCR の全面刷新。

## 参照

- `specs/021-visual-pdf-understanding-prod/spec.md`
- `docs/production-gate-strategy.md`
- `docs/loop-engineering.md`
