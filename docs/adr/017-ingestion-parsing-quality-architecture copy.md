# ADR-017: 取り込み(パース〜チャンク化)の品質アーキテクチャ — 「何が来ても高品質」に耐える設計

- **Status**: Proposed(設計記録のみ / 実装は未着手・本ADRでは書かない)
- **Date**: 2026-07-05
- **Owner**: プロダクト(wer.inc)
- **Scope of this ADR**: 顧客企業から**何が来るか事前に分からない**多様なドキュメントを、取り込み〜チャンク
  化まで**高品質**に扱うための *方針* を凍結する。具体のライブラリ選定・エンドポイント・UI・コードは書かない
  (実装は後続 issue / 別ADR)。
- **Related**:
  - 現行実装: `src/raku_rag/providers/parsers.py`(`CompositeParser`), `src/raku_rag/production.py:119`,
    `src/raku_rag/workers/ingestion.py`(PDFレンダリング/OCR経路), `src/raku_rag/providers/chunkers.py`
    (`SentenceChunker`), `src/raku_rag/providers/aws_visual.py`(Textract), `apps/answer-service/server.py:295`
    (`parser_mode: aws_only`, `allowed_parser_providers: [aws_textract, tesseract]`)
  - 安全モデル: `CLAUDE.md` §002 ハードルール(AI出力は常に draft / 高リスクは承認済み+有効な引用が要る),
    レビュー導線 `/reviews`
  - 既存判断: `adr.md`(ADR-001..006, no-LangChain critical path), `docs/adr/015-answer-workspace-approach.md`
    (VLM を "推論+引用+構造化" で使う姿勢), メモリ「Visual/VLM is a deferred stub」

---

## 1. 何をやりたいか(Intent)

> **顧客から何が来ても(事前に形式・品質が分からなくても)、高品質にナレッジ化したい。**

- 対象は製造現場のドキュメント全般: 手順書 / 作業標準 / 検査記録 / 帳票 / トラブル報告 / 議事録 / 図面 /
  スキャンPDF / 印鑑・手書き注記つきの紙 / Excel台帳 / Word / PPT など。
- 顧客企業ごとに何が来るか**予測できない**。「このフォーマットだけ対応」では不十分で、**未知の入力に対して
  破綻せず、高品質か、少なくとも "低品質だと分かる" 状態**にしたい。
- この製品は安全系(高リスク回答が引用でゲートされる)なので、**誤った/文字化けした抽出が黙って回答の土台に
  なる**のが最悪。品質は "読めた率" だけでなく **"読めなかったものを取りこぼさない"** ことを含む。

---

## 2. 今の課題(Current State & Problems)

### 2.1 現行パイプライン(事実)

- **テキスト系パーサ**: `CompositeParser([TextParser, DocxParser, SpreadsheetParser])`(`production.py:119`)
  - txt/md/html → `TextParser`(NFKC正規化・HTMLタグ除去)
  - docx → `DocxParser`(python-docx)
  - xlsx/csv → `SpreadsheetParser`(openpyxl/stdlib csv)。**1セル=1ブロック**で
    `"{sheet}!R{row}C{col} {header}: {value}"` のセルアンカー付き(FR-MFG-002、セル単位引用)
- **PDF/画像**: `CompositeParser` に PDF パーサは無い。`pypdfium2` でページを画像化
  (`workers/ingestion.py:1159`)→ **OCR** に回す。stg は `parser_mode: aws_only` /
  `allowed_parser_providers: [aws_textract, tesseract]`(`server.py:295`)= **AWS Textract** が担当。
- **チャンク化**: 自前 `SentenceChunker`(`chunkers.py`)。段落(`\n\n`)→文境界→文字数バジェット詰め
  (種別プロファイル: default 400字 / work_instruction 520/80 / inspection 460/60 / quality_report 700/100 …)。
- **`Parser` インターフェイスは `parse(raw, content_type) -> str`(テキストのみ)**。構造(表・見出し・読み順)は
  返さない。
- **VLM は現状スタブ**(`ExtractiveVLMProvider` 相当・決定論オフライン。実ビジョンモデル未接続)。

### 2.2 具体的な弱点(何が高品質にならないか)

| 入力 | 現状の問題 |
|---|---|
| **複雑な図面(CAD)** | テキスト層が無い/アウトライン化/ラスタが多く、抽出は空 or 断片。OCRしても密な図面は低精度。**寸法・公差・吹き出し・表題欄の意味は取れない** |
| **表データ(PDF)** | 現行は OCR で平坦化 → **行・列・セル構造が失われる**。`SentenceChunker` は表を途中分断しがち |
| **スキャン日本語** | OCRエンジン依存。既定OCRの日本語精度・**縦書き**が弱点。品質が入力次第でばらつく |
| **壊れたCMapのデジタルJP PDF** | ToUnicode 無し/CIDキーのフォント → テキスト抽出が**文字化け/CIDコード**に。検知せず取り込むと汚れる |
| **手書き注記・印鑑(ハンコ)・ルビ** | OCR全般が苦手。製造現場の紙で頻出 |
| **品質の可視化が無い** | **抽出が低品質でも "成功" として黙ってチャンク化**され得る。安全ゲートに汚染が回る経路 |

### 2.3 構造的な制約

- **インターフェイスがテキストのみ** → 表・レイアウト等の "構造" を下流(チャンカー/引用)に運べない。
- **xlsx のセルアンカー(FR-MFG-002)は独自要件** → 汎用パーサでは置換不可、維持が必要。
- **運用が minimalSpec(コスト最小・小Fargate)** → 重い依存/モデル推論を無制限には積めない
  (メモリ「Use only the stg environment」= 新スタック増設は不可、コスト増に敏感)。
- **決定論性**を追跡している(`parser_version` / `chunking_config_version`)→ ML依存を足すと再現性管理に一手間。

---

## 3. 検討した選択肢と評価

### 3.1 単一の "魔法パーサ" は存在しない(前提)

Docling / Unstructured / pypdfium2 いずれも万能ではない。特に **図面・縦書き・手書き・壊れCMap** はどのツール
でも穴が残る。→ **ツール選定ではなくアーキテクチャで解く**、が本ADRの中心判断。

### 3.2 Docling の実測評価(裏取り済み)

- **速度は思ったほど重くない**: CPU(x86)で1ページ **中央値0.79秒 / 平均3.1秒**(平均はOCR要・複雑ページで
  釣り上がる)。**GPUは任意**(CPU-only を公式サポート、GPUは約6倍速の "あれば速い")。
  出典: Docling Technical Report(arXiv 2408.09869)。
- **本当に重いのは依存/イメージ/RAM**: **torch(PyTorch)必須**+モデル重み(layout+TableFormer)。
  → **Fargateイメージが ~1GB級に肥大**・推論RAM(概ね1〜2GB余裕)。minimalSpec では要考慮(CVE面も増)。
- **解決するのは主に "表"**: TableFormer が行・列・ヘッダ・セルを構造化(DataFrame等で出せる)。
- **日本語は "Docling で解決" ではなく "OCRエンジン選定の問題"**: Docling は OCR を外部委譲(既定EasyOCR /
  RapidOCR / Tesseract 等)。**EasyOCRは縦書き日本語が弱い**(既知issue)。CJKは PaddleOCR 等の特化が要る。
  Docling のレイアウトモデルも主に欧文(DocLayNet)学習。
- **図面(CAD)は解決しない**: 文書レイアウトの道具であり、図面は "picture領域" として中身を解釈しない。

出典: Docling Technical Report(arXiv 2408.09869) / Docling Installation docs / "Why OCR for CJK Languages
Is Still a Hard Problem (2026)" / EasyOCR 縦書きJP issue / IBM Granite-Docling(VLMベース文書理解)。

### 3.3 3課題への「解決するか」判定

| 課題 | Docling で解決? | 実際の本命 |
|---|---|---|
| 表 | ✅ かなり解決(TableFormer) | Docling TableFormer / Textract TABLES |
| 日本語(スキャン/縦書き) | 🔺 半分・エンジン依存 | **JP対応OCLの選定**(PaddleOCR / Google DocAI / Azure DI / Tesseract-jpn)+ 縦書き・文字化け振り分け |
| 図面(CAD) | ❌ 解決しない | **VLM(視覚モデル)解釈** or OCLで文字注記のみ + 人手注釈 |

---

## 4. 決定(Decision)

### D1 — 単一パーサではなく「品質ゲート主導のルーティング + フォールバック」アーキテクチャにする

「何が来ても高品質」を **1ツールで** ではなく **システムで** 保証する。核心原則:

> **「完璧に読める」は保証できない。しかし「低品質な抽出が黙って回答に混入しない」は保証できる。**
> 読めなかったら **"読めなかった" と大声で言って人に回す(fail-loud + HITL)**。

構成(層):

```
入力(何でも)
  ├─ ① 判別(ページ単位): デジタル/スキャン, テキスト層有無, 表, 図面, 縦書き, 言語,
  │                       文字化け(CID/非日本語比)率
  ├─ ② 適材適所の抽出:
  │     クリーンなデジタル → pypdfium2 ネイティブテキスト(安・速)
  │     表               → Docling TableFormer / Textract TABLES(構造化)
  │     スキャン日本語     → JP対応OCR(PaddleOCR / Google DocAI 等)
  │     図面/手書き/難物   → VLM(視覚モデル)で解釈
  ├─ ③ 品質スコア: テキスト歩留まり, OCR信頼度, 文字化け率, 被覆率
  ├─ ④ しきい値判定: 高信頼→取り込み / 低信頼→一段強いエンジンへフォールバック→なお低ければ⑤
  └─ ⑤ 人手確認(HITL): 既存レビュー導線に「低品質・要確認」で送る(黙って回答に流さない)
```

### D2 — VLM(視覚モデル)を「何でも来い」の万能フォールバックに位置づける(ただし要ガード)

- cheap な決定論経路で easy な大多数を捌き、**難物の尻尾だけ VLM に回す**(図面・手書き・縦書き・変レイアウト)。
- VLM は **幻覚(無い文字の "創作")リスク** があるため、安全系KBに入れる前に **根拠照合・信頼度・重要項目は
  HITL** で縛る(ADR-015 の "推論+引用+構造化・no-train・draftのみ" 姿勢を踏襲)。
- 現状 VLM はスタブ。**本物化(Claude/Gemini vision 等)** が D2 の前提作業。

### D3 — xlsx/txt/docx の現行自前経路は維持する

- セルアンカー(FR-MFG-002)等、軽くて良い部分は置き換えない。Docling等の導入は **PDF/図面/スキャン領域に限定**。

### D4 — 追加エンジンは opt-in・非同期・コスト境界つきで足す

- torch/OCR/VLM は **opt-in プロバイダ**(既存の embedding provider opt-in と同じ流儀)として、**非同期ワーカー**に
  載せる。同期取り込み経路の UX/コストを守る。minimalSpec を壊さない(必要な難物だけ重い経路へ)。

### 却下した代替案(Rejected alternatives)

- **A1 — Docling(または任意の単一パーサ)で全部やる。** *却下*: 図面・縦書き・手書きが埋まらない。日本語は
  結局OCLエンジン選定の問題。単一ツールでは "何が来ても" を満たせない。
- **A2 — 現状維持(全PDFを Textract OCL)。** *却下*: デジタルPDFまで毎回OCL(コスト/遅延/誤り)。表構造喪失。
  品質ゲートが無く、低品質が黙って回答へ。
- **A3 — 重いパイプライン(多エンジン+VLM+信頼度+HITL)を最初から全部積む。** *却下(順序として)*: minimalSpec
  で過投資。まず品質ゲート(fail-loud)で "高品質保証" を先に立て、自動処理率は段階的に上げる(§5)。

---

## 5. 段階導入(Phased Plan / 実装は後続)

| Phase | 内容 | 価値 | コスト | 「何でも来い」への効き |
|---|---|---|---|---|
| **A(最優先)** | **品質スコア + しきい値ゲート + HITL送り**。低品質を「要確認」でレビュー行きに。パーサはまだ増やさない | ★★★(安全の核) | 小 | **保証を先に確立**(黙って汚染しない) |
| **B** | pypdfium2 ネイティブ抽出 / 表→Docling・Textract TABLES / スキャンJP→JP対応OCL + 縦書き・文字化け振り分け | ★★(自動処理率↑) | 中 | 自動で捌ける割合を拡大 |
| **C** | **VLM 本物化**し、難物・低信頼ページの万能フォールバックに(図面もここ)。根拠照合+HITLで安全に | ★★★(実現) | 中〜大 | 尻尾(未知/難物)を回収 |

**要点**: 「何が来ても高品質」の *保証* は **Phase A(fail-loud + HITL)** で先に立つ。B/C は *自動でさばける割合* を
上げる改善。いきなり全OCL/VLMを積む必要はない。

---

## 6. 帰結(Consequences)

**良くなること**
- 未知フォーマットに対して**破綻しない**(最悪でも "要確認" で人に回る)。安全ゲートに汚染が回らない。
- 表・図面・スキャン日本語など、これまで落ちていた領域を段階的に自動化。
- 引用精度(構造対応チャンク)向上 → 高リスク回答の根拠品質に直結。

**コスト・リスク**
- OCL/VLM/torch を足すと **イメージ肥大・推論コスト・非同期化** が必要(§2.3 の minimalSpec 制約)。→ opt-in +
  難物限定で抑制(D4)。
- **VLM 幻覚**リスク → 根拠照合・信頼度・HITL(D2)。
- ML依存で**決定論/再現性**に一手間(`parser_version` 管理)。
- 日本語OCL(特に縦書き・手書き・印鑑)は**残差**が残る前提。重要項目は HITL 設計で受ける。

**据え置き(この製品では当面やらない)**
- 図面の完全自動理解(寸法/公差の機械可読化)。VLM解釈 + 人手注釈で受ける。
- カスタム画像モデルの学習(ADR-015 の no-train 姿勢を踏襲)。

---

## 7. 未解決の論点(Open Questions)

1. **品質しきい値の定義**: どの指標(テキスト歩留まり / OCL信頼度 / 文字化け率 / 被覆率)で "要確認" に落とすか。
2. **JP-OCLエンジンの選定**: PaddleOCR / Google Document AI / Azure DI / Textract(CJK対応の現状は要検証) /
   Tesseract-jpn のどれを既定にするか。縦書き対応の担保。
3. **VLM の採用モデルと単価上限**: Bedrock Claude vision / Gemini。難物だけに回すルーティング閾値と月次コスト上限。
4. **構造の受け渡し**: `Parser` インターフェイスをテキスト専用から "構造つき" にどう拡張するか(下流チャンカー/引用への影響)。
5. **既存取り込み済み文書の再処理**: 品質ゲート導入後、過去分をどう再評価(reindex)するか。

---

## 8. 決めたら次にやること(このADRの外)

- Phase A の設計 issue(品質スコア + ゲート + レビュー送り。既存 `/reviews` とメタデータ拡張)。
- 代表PDF(デジタル手順書 / スキャン検査表 / 縦書き帳票 / 図面 / 印鑑つき)を通した **現状ベースラインの実測分類**
  ("素で読める / OCL要 / 構造エンジン要 / 人手要")。
