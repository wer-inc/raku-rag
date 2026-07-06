方針は **Docling-first, Quality-gated, Provider-pluggable** です。

---

# ADR-018: RAG 取り込み品質アーキテクチャ — Docling-first / Quality-gated / Provider-pluggable

* **Status**: Accepted
* **Date**: 2026-07-05
* **Accepted**: 2026-07-06（実装ブランチ `018-ingestion-quality-architecture` にて Phase A/B + §4.2/§9.4 + Phase C-E スキャフォールドを実装・検証）
* **Owner**: プロダクト / wer.inc
* **Scope**: 顧客企業から事前に形式・品質が分からない文書群を、RAG の取り込み、パース、構造化、チャンク化、引用可能化まで安全に扱うための品質アーキテクチャを定める。
* **Non-goals**:

  * 本 ADR では具体的なエンドポイント、UI 実装、コード実装、クラウド設定値は決めない。
  * 図面の寸法・公差・幾何公差を完全に機械可読化することは当面の対象外とする。
  * カスタム画像モデルの学習は当面行わない。
* **Related**:

  * 現行実装: `src/raku_rag/providers/parsers.py` (`CompositeParser`)
  * 現行実装: `src/raku_rag/production.py:119`
  * 現行実装: `src/raku_rag/workers/ingestion.py`
  * 現行実装: `src/raku_rag/providers/chunkers.py` (`SentenceChunker`)
  * 現行実装: `src/raku_rag/providers/aws_visual.py` (`Textract`)
  * 現行実装: `apps/answer-service/server.py:295`
  * 安全モデル: `CLAUDE.md` §002
  * レビュー導線: `/reviews`
  * 既存 ADR: ADR-001..006, ADR-015
  * 既存メモリ: `Visual/VLM is a deferred stub`

---

## 1. Decision Summary

本 ADR では、RAG 取り込みの品質方針を次のように決定する。

> **Docling を構造化パースの第一候補 provider とする。
> ただし、システムの正本は DoclingDocument ではなく、自社定義の `ParsedDocument` とする。
> 低品質な抽出結果は通常 index に混ぜず、quarantine し、必要に応じて HITL に送る。**

本 ADR の中心判断は、単なるパーサ選定ではない。

本当に守るべき性質は次である。

> **完璧に読めることは保証できない。
> しかし、低品質な抽出が黙って回答の土台に混入しないことは保証する。**

このため、取り込みパイプラインは以下の原則で設計する。

1. **Docling-first**
   PDF / DOCX / PPTX / 画像系ドキュメントの構造化パースは Docling を第一候補にする。

2. **Quality-gated**
   抽出結果は必ず品質評価を通し、`accepted` / `review_required` / `rejected` / `draft_visual` に分類する。

3. **Provider-pluggable**
   OCR、VLM、Textract、Google Document AI、Azure Document Intelligence、PaddleOCR などは差し替え可能な provider として扱う。

4. **Fail-loud + HITL**
   読めなかったもの、怪しいもの、構造が壊れているものは、黙って index に入れず、レビュー対象として明示する。

5. **Citation-first**
   高リスク回答に使える情報は、ページ、bbox、セル、表範囲、レビュー承認状態などの引用 anchor を持つものに限定する。

---

## 2. Background / Intent

顧客企業から投入される文書は、事前に形式・品質・レイアウトを予測できない。

対象には次が含まれる。

* 手順書
* 作業標準
* 検査記録
* 品質帳票
* トラブル報告
* 議事録
* 図面
* スキャン PDF
* 印鑑・手書き注記つきの紙
* Excel 台帳
* Word
* PowerPoint
* HTML / Markdown / txt
* 写真・画像化された文書

この製品では、安全系回答のために引用とレビュー導線がある。したがって、単に「読めたテキストを増やす」ことよりも、次が重要である。

> **壊れた抽出、文字化け、表崩れ、誤 OCR、VLM の創作が、通常の RAG index に紛れ込まないこと。**

RAG における取り込み品質の失敗は、回答時には検知しづらい。
一度汚い chunk が vector index に混入すると、後続の retrieval、rerank、answer generation、引用生成のすべてが汚染される。

そのため、本 ADR は「何でも自動で読む」ことより先に、**読めないものを読めないと扱う仕組み**を決める。

---

## 3. Current State

### 3.1 現行パイプライン

現行の取り込みパイプラインは以下の構成である。

* `CompositeParser([TextParser, DocxParser, SpreadsheetParser])`
* txt / md / html は `TextParser`
* docx は `DocxParser`
* xlsx / csv は `SpreadsheetParser`
* PDF は `CompositeParser` に含まれず、`pypdfium2` でページ画像化して OCR 経路に回す
* stg では `parser_mode: aws_only` / `allowed_parser_providers: [aws_textract, tesseract]`
* chunking は自前 `SentenceChunker`
* `Parser` interface は `parse(raw, content_type) -> str`
* VLM は現状 stub

### 3.2 現行のよい点

現行には維持すべき強みがある。

特に xlsx / csv のセル単位処理は重要である。

```text
{sheet}!R{row}C{col} {header}: {value}
```

この形式は、製造現場の Excel 台帳に対して、セル単位の引用、レビュー、監査をしやすい。
これは汎用 parser では自然に満たせないプロダクト固有要件であるため、置換せずに維持する。

### 3.3 現行の主な問題

| 領域               | 問題                                                   |
| ---------------- | ---------------------------------------------------- |
| Parser interface | `str` しか返さないため、ページ、bbox、表、見出し、読み順、セル anchor を下流に運べない |
| PDF              | PDF がネイティブ構造抽出ではなく、基本的に画像化 + OCR 経路に寄っている            |
| 表                | 表構造が文字列へ平坦化され、行・列・ヘッダ・セル結合・範囲引用が落ちる                  |
| チャンク化            | `SentenceChunker` が表、箇条書き、図表説明、フォーム項目を途中で壊す          |
| 日本語 OCR          | OCR engine 依存で、スキャン、縦書き、手書き、印鑑、低解像度に弱い               |
| 図面               | CAD / 図面の寸法、公差、吹き出し、表題欄の意味理解は通常 OCR では困難             |
| 品質可視化            | 低品質抽出でも成功扱いになり、通常 index に混入し得る                       |
| 再現性              | parser / OCR / VLM / model version の追跡が弱い            |
| 安全ゲート            | 引用可能な情報と、未確認・低信頼な情報の境界が不十分                           |

---

## 4. 技術前提

### 4.1 Docling の位置づけ

Docling は、PDF、DOCX、XLSX、PPTX、HTML、画像など複数形式を扱える文書変換ツールであり、Docling JSON / DoclingDocument という構造化表現を持つ。公式ドキュメントでは PDF、DOCX、XLSX、PPTX、HTML、画像などの対応が示されている。([Docling Project][1])

Docling は layout analysis と table structure recognition に specialized AI models を使う設計で、技術レポートでは DocLayNet と TableFormer が中核として説明されている。([arXiv][2])

Docling は lossless JSON serialization と、Markdown / HTML などの lossy export を持つ。したがって、RAG 内部の正本としては Markdown ではなく JSON / block 構造を使うべきである。([arXiv][3])

### 4.2 Docling と OCR の責務分離

Docling は OCR 機能を持つが、OCR engine は外部依存として選択・設定する。公式 installation docs では Tesseract を Docling と使う場合のインストールや `TESSDATA_PREFIX` の設定が説明されている。([Docling Project][4])

したがって、本 ADR では次を前提とする。

> **Docling は構造化パースの第一候補である。
> しかし、日本語 OCR の品質責任を Docling 単体に持たせない。**

### 4.3 Textract の位置づけ

Amazon Textract は英語、スペイン語、ドイツ語、イタリア語、フランス語、ポルトガル語をサポート対象としており、公式 best practices でもサポート言語に日本語は含まれていない。([AWS ドキュメント][5])

したがって、日本語製造ドキュメントの既定 OCR として Textract を置くのは避ける。

Textract は以下のように扱う。

* 英語 / 欧州言語中心の帳票やフォームでの候補
* TABLES / FORMS / bbox / confidence を返す補助 provider
* 日本語 OCR の既定候補ではない

### 4.4 日本語 OCR 候補

日本語 OCR については、Docling ではなく OCR provider の選定問題として扱う。

候補には以下がある。

* Google Document AI
* Azure Document Intelligence / Azure Vision OCR
* PaddleOCR
* Tesseract-jpn
* RapidOCR
* 必要に応じてその他の商用 OCR

Google Document AI の Enterprise Document OCR は、200 以上の言語、手書きテキスト抽出、文書 readability の quality assessment を提供すると説明されている。([Google Cloud Documentation][6])

Azure Vision OCR は、印刷テキストで日本語を含む多数言語、手書きテキストで日本語を含む複数言語をサポートしている。([Microsoft Learn][7])

Azure Document Intelligence の layout model は OCR と deep learning models を組み合わせ、テキスト、表、selection marks、document structure を抽出する API として説明されている。([Microsoft Learn][8])

PaddleOCR は PP-OCRv6 で中国語、英語、日本語、ラテン系言語を含む 50 言語対応を掲げており、PaddleOCR 公式 docs でも多言語 OCR と日本語対応が説明されている。([PaddlePaddle][9])

ただし、対応言語に Japanese と書かれていることと、製造現場の縦書き、斜めスキャン、かすれ、手書き注記、印鑑、図面注記で実用精度が出ることは別である。
最終判断は Golden Eval Pack による実測で行う。

---

## 5. Design Principles

### P1. 正本は provider 出力ではなく、自社 `ParsedDocument`

Docling は第一候補 provider とするが、システム内部の正本は DoclingDocument ではなく、自社定義の `ParsedDocument` とする。

理由は以下である。

* Docling 以外の provider を併用する
* OCR provider を差し替える
* VLM 出力を draft として混ぜる
* Excel セル anchor を保持する
* 引用、レビュー、品質ゲート、チャンク化を provider 非依存にする
* 将来 parser を変更しても下流を壊さない

つまり、内部 contract はこうする。

```text
Provider output
  ├─ DoclingDocument
  ├─ Textract JSON
  ├─ Google Document AI result
  ├─ Azure Document Intelligence result
  ├─ PaddleOCR result
  ├─ Existing SpreadsheetParser output
  └─ VLM draft result
        ↓ normalize
ParsedDocument
        ↓ quality gate
Accepted / Review Required / Rejected / Draft Visual
        ↓
Structure-aware chunks
        ↓
Index / Review / Quarantine
```

### P2. Markdown は正本にしない

Docling Markdown は人間が読みやすく、embedding 用 serialization として便利である。
しかし、Markdown はすべての構造情報を保持できる正本ではない。

本システムでは以下の役割分担にする。

| 表現                      | 役割                 |
| ----------------------- | ------------------ |
| `ParsedDocument`        | 正本                 |
| provider raw output     | 再現性・監査用            |
| Markdown                | 検索用・表示用の派生物        |
| `text_for_embedding`    | embedding 最適化済み派生物 |
| image crop / page image | 視覚引用・レビュー用         |

### P3. 低品質抽出は通常 index に入れない

`review_required` または `rejected` の抽出結果は、通常検索 index に入れない。

レビュー導線に送るだけでは不十分である。
通常 index に入ってしまえば、RAG が retrieval して回答に使ってしまう可能性がある。

したがって、品質状態と index 可否を明示的に分ける。

| Status                   | Primary retrieval | Review queue | High-risk answer citation | 備考            |
| ------------------------ | ----------------: | -----------: | ------------------------: | ------------- |
| `accepted`               |                 可 |           任意 |                         可 | 通常利用可能        |
| `accepted_with_warnings` |                 可 |           任意 |                     条件付き可 | 軽微な警告あり       |
| `review_required`        |                不可 |           必須 |                        不可 | quarantine    |
| `rejected`               |                不可 |           任意 |                        不可 | 保存のみ          |
| `draft_visual`           |                不可 |           必須 |                        不可 | VLM 等の未承認視覚解釈 |
| `manual_approved`        |                 可 |            済 |                         可 | 人手承認後         |

### P4. 失敗は例外ではなく通常状態として扱う

未知形式、壊れ PDF、低品質スキャン、手書き、図面は普通に来る。
したがって、parser failure は異常系ではなく、品質状態として扱う。

失敗時に stack trace を残すだけでは不十分である。
ユーザーや reviewer に対して、次を説明できる必要がある。

* どのページが読めなかったか
* なぜ低品質と判定したか
* どの provider を試したか
* どの provider が失敗したか
* 次に何をすればよいか
* 通常回答に使われていないこと

### P5. 自動処理率より false accept 最小化を優先する

初期段階では、良い文書を review に回しすぎる false reject より、悪い抽出を accepted にしてしまう false accept のほうが危険である。

したがって、Phase A では以下を優先する。

> **低品質なのに accepted になる率を最小化する。**

自動処理率は Phase B 以降で改善する。

---

## 6. Target Architecture

### 6.1 全体構成

```text
Input document
  ↓
File normalization / MIME detection / hash
  ↓
Page-level preflight analysis
  - digital vs scanned vs hybrid
  - text layer availability
  - language guess
  - table-heavy detection
  - drawing / figure-heavy detection
  - vertical text / handwriting / seal suspicion
  - mojibake / CID / broken CMap suspicion
  ↓
Routing
  - clean digital document
  - table-heavy document
  - scanned Japanese document
  - Office document
  - spreadsheet
  - drawing / visual-heavy document
  - unknown / suspicious
  ↓
Provider extraction
  - Docling-first structured parser
  - existing SpreadsheetParser
  - native text extraction
  - JP OCR provider
  - Textract where appropriate
  - VLM draft fallback
  ↓
Normalize to ParsedDocument
  ↓
Quality scoring
  ↓
Quality gate
  ├─ accepted
  ├─ accepted_with_warnings
  ├─ review_required
  ├─ rejected
  └─ draft_visual
  ↓
Structure-aware chunking
  ↓
Index / Quarantine / Review
```

### 6.2 Page-level routing

取り込み時には、文書単位だけでなくページ単位で routing する。

1 つの PDF の中に、通常本文、表、スキャンページ、図面、手書き注記ページが混在することがあるためである。

| Page type                       | Primary route                         | Fallback                                  |
| ------------------------------- | ------------------------------------- | ----------------------------------------- |
| clean digital text              | Docling / native text extraction      | OCR compare                               |
| digital but mojibake suspicious | Docling + OCR compare                 | review_required                           |
| table-heavy PDF                 | Docling TableFormer                   | Azure DI / Google DocAI / Textract TABLES |
| scanned Japanese                | JP OCR provider                       | alternate OCR / review_required           |
| vertical Japanese               | JP OCR provider with vertical support | VLM draft + HITL                          |
| handwritten note                | OCR if supported                      | VLM draft + HITL                          |
| seal / stamp                    | visual marker detection               | HITL                                      |
| drawing / CAD                   | OCR for visible text + VLM draft      | HITL                                      |
| image-only unknown              | OCR + visual classification           | review_required                           |
| spreadsheet                     | existing SpreadsheetParser            | manual review                             |
| Office document                 | Docling-first or existing parser      | review_required                           |

### 6.3 Provider routing is traceable

すべての provider 実行は `route_trace` に残す。

例:

```json
{
  "route_trace": [
    {
      "stage": "preflight",
      "result": "scanned_japanese_table",
      "signals": ["no_text_layer", "table_heavy", "language_guess_ja"]
    },
    {
      "stage": "extract",
      "provider": "docling",
      "result": "partial",
      "reason": "low_ocr_confidence"
    },
    {
      "stage": "fallback",
      "provider": "azure_document_intelligence",
      "result": "accepted"
    }
  ]
}
```

この trace は、review、debug、再処理、顧客説明に使う。

---

## 7. `ParsedDocument` Contract

### 7.1 Contract 方針

`ParsedDocument` は、parser provider 非依存の内部中間表現である。

必須要件は以下。

* ページ単位の情報を持てる
* block 単位の情報を持てる
* 表構造を壊さず保持できる
* Excel セル anchor を保持できる
* bbox / page / sheet / row / col などの引用 anchor を持てる
* provider / model / version / config を保持できる
* confidence と quality reason を保持できる
* VLM draft と OCR result を区別できる
* chunking 前の正本として保存できる

### 7.2 Conceptual schema

実装言語や class 名は後続 issue で決めるが、概念 schema は以下とする。

```json
{
  "schema_version": "parsed_document.v1",
  "source": {
    "document_id": "doc_...",
    "source_hash": "sha256:...",
    "filename": "inspection_report.pdf",
    "mime_type": "application/pdf",
    "size_bytes": 1234567
  },
  "ingestion": {
    "run_id": "ing_...",
    "profile": "default",
    "created_at": "2026-07-05T00:00:00Z",
    "parser_contract_version": "v1",
    "chunking_contract_version": "v1"
  },
  "provider_runs": [
    {
      "provider": "docling",
      "provider_version": "...",
      "model_versions": {
        "layout": "...",
        "table": "..."
      },
      "config_hash": "sha256:...",
      "started_at": "...",
      "finished_at": "...",
      "status": "success"
    }
  ],
  "pages": [],
  "blocks": [],
  "tables": [],
  "figures": [],
  "quality": {},
  "route_trace": []
}
```

### 7.3 Page

```json
{
  "page_id": "p_1",
  "page_no": 1,
  "width": 2480,
  "height": 3508,
  "unit": "px",
  "page_image_ref": "s3://...",
  "detected_languages": ["ja"],
  "page_type": "scanned_table",
  "signals": {
    "has_text_layer": false,
    "is_scanned": true,
    "is_table_heavy": true,
    "is_drawing_like": false,
    "vertical_text_suspected": false,
    "handwriting_suspected": true,
    "seal_suspected": true,
    "mojibake_suspected": false
  },
  "quality": {
    "status": "review_required",
    "reasons": ["handwriting_suspected", "low_ocr_confidence_p10"]
  }
}
```

### 7.4 Block

```json
{
  "block_id": "b_123",
  "kind": "paragraph",
  "text": "作業前に主電源を停止すること。",
  "normalized_text": "作業前に主電源を停止すること。",
  "page_no": 3,
  "bbox": [120, 240, 1800, 360],
  "reading_order": 12,
  "confidence": 0.98,
  "source_anchor": {
    "type": "page_bbox",
    "page_no": 3,
    "bbox": [120, 240, 1800, 360]
  },
  "provenance": {
    "provider": "docling",
    "method": "native_or_ocr",
    "provider_version": "...",
    "model_version": "...",
    "route": "docling_first"
  },
  "quality": {
    "status": "accepted",
    "reasons": []
  }
}
```

### 7.5 Block kinds

最低限、以下の block 種別を扱う。

| kind             | 用途          |
| ---------------- | ----------- |
| `title`          | 文書タイトル      |
| `heading`        | 見出し         |
| `paragraph`      | 本文          |
| `list_item`      | 箇条書き        |
| `table`          | 表全体         |
| `table_row`      | 表の行         |
| `table_cell`     | 表セル         |
| `form_field`     | フォーム項目      |
| `figure`         | 図・画像        |
| `chart`          | グラフ         |
| `drawing`        | 図面・CAD 的ページ |
| `caption`        | 図表キャプション    |
| `header`         | ページヘッダ      |
| `footer`         | ページフッタ      |
| `handwriting`    | 手書き注記       |
| `seal`           | 印鑑・スタンプ     |
| `visual_summary` | VLM による視覚要約 |
| `unknown`        | 分類不能        |

### 7.6 Table

表は Markdown 文字列だけで保持しない。
構造として保持する。

```json
{
  "table_id": "t_1",
  "page_no": 4,
  "bbox": [100, 500, 2300, 2400],
  "columns": [
    {"index": 0, "text": "検査項目"},
    {"index": 1, "text": "基準"},
    {"index": 2, "text": "結果"}
  ],
  "cells": [
    {
      "row": 0,
      "col": 0,
      "rowspan": 1,
      "colspan": 1,
      "text": "外観",
      "bbox": [120, 560, 520, 650],
      "confidence": 0.96,
      "is_header": true
    }
  ],
  "quality": {
    "table_structure_confidence": 0.91,
    "status": "accepted"
  },
  "provenance": {
    "provider": "docling",
    "method": "table_structure_recognition"
  }
}
```

### 7.7 Spreadsheet anchors

xlsx / csv は現行 `SpreadsheetParser` の思想を維持する。
ただし、出力先は `str` ではなく `ParsedDocument` に揃える。

```json
{
  "block_id": "cell_...",
  "kind": "table_cell",
  "text": "sheet1!R12C4 検査結果: OK",
  "source_anchor": {
    "type": "spreadsheet_cell",
    "sheet": "sheet1",
    "row": 12,
    "col": 4,
    "header": "検査結果"
  },
  "provenance": {
    "provider": "spreadsheet_parser",
    "method": "cell_anchor"
  },
  "quality": {
    "status": "accepted"
  }
}
```

---

## 8. Quality Gate

### 8.1 Quality status

抽出結果は必ず品質状態を持つ。

| Status                   | 意味                            |
| ------------------------ | ----------------------------- |
| `accepted`               | 通常の RAG 回答に利用可能               |
| `accepted_with_warnings` | 利用可能だが軽微な警告あり                 |
| `review_required`        | 通常回答には利用不可。人手確認が必要            |
| `rejected`               | 利用不可                          |
| `draft_visual`           | VLM 等による未承認視覚解釈。通常回答・高リスク引用不可 |
| `manual_approved`        | 人手承認済み。通常回答に利用可能              |

### 8.2 Quality score は単一 scalar にしない

`quality_score = 0.82` だけでは不十分である。

品質劣化には種類がある。

* OCR は読めているが読み順が壊れている
* 本文は読めているが表構造が壊れている
* 文字数は多いが CMap 壊れで文字化けしている
* 表はあるがセル境界が崩れている
* ハンコ・手書き注記が落ちている
* 図面注記は読めたが寸法線との対応が分からない
* VLM がもっともらしい説明を作ったが根拠 crop がない

したがって、品質は vector として持つ。

```json
{
  "quality": {
    "status": "review_required",
    "overall": 0.71,
    "dimensions": {
      "text_yield": 0.92,
      "mojibake_risk": 0.04,
      "ocr_confidence_p10": 0.63,
      "ocr_confidence_p50": 0.88,
      "layout_confidence": 0.78,
      "reading_order_risk": 0.22,
      "table_structure_confidence": 0.41,
      "visual_coverage": 0.69,
      "language_consistency": 0.93
    },
    "flags": {
      "handwriting_detected": true,
      "seal_detected": true,
      "vertical_text_suspected": false,
      "drawing_like": false
    },
    "reasons": [
      "low_table_structure_confidence",
      "handwriting_detected",
      "seal_detected"
    ]
  }
}
```

### 8.3 Quality dimensions

最低限、以下の dimension を持つ。

| Dimension                    | 説明                            |
| ---------------------------- | ----------------------------- |
| `text_yield`                 | ページに対して抽出テキストが十分あるか           |
| `empty_page_risk`            | 非空ページなのに抽出が空ではないか             |
| `mojibake_risk`              | CID、ToUnicode 欠落、`�`、異常文字比率など |
| `language_consistency`       | 期待言語と抽出言語が一致しているか             |
| `ocr_confidence_p10`         | OCR confidence の低位 percentile |
| `ocr_confidence_p50`         | OCR confidence の中央値           |
| `layout_confidence`          | レイアウト分割の信頼度                   |
| `reading_order_risk`         | 読み順崩れリスク                      |
| `table_structure_confidence` | 行・列・ヘッダ・セル構造の信頼度              |
| `cell_anchor_coverage`       | セル単位 anchor が保持されているか         |
| `visual_coverage`            | 画像上の意味領域に対して抽出がどれだけ被覆しているか    |
| `handwriting_detected`       | 手書き注記があるか                     |
| `seal_detected`              | 印鑑・スタンプがあるか                   |
| `vertical_text_suspected`    | 縦書きが疑われるか                     |
| `drawing_like`               | 図面・CAD 的ページか                  |
| `provider_error`             | provider 失敗があったか              |

### 8.4 Hard fail / review 条件

以下は原則として `review_required` または `rejected` に落とす。

| 条件                                     | 状態                               |
| -------------------------------------- | -------------------------------- |
| 非空ページなのに抽出テキストがほぼ空                     | `review_required`                |
| CMap / CID / mojibake リスクが高い           | `review_required`                |
| OCR confidence 下位 percentile が低い       | `review_required`                |
| 表ページなのに table structure confidence が低い | `review_required`                |
| 図面ページで OCR 文字列しか得られていない                | `review_required`                |
| VLM のみで作られた内容                          | `draft_visual`                   |
| VLM 出力に根拠 crop / bbox がない              | `draft_visual`                   |
| provider がすべて失敗                        | `rejected` または `review_required` |
| 手書き・印鑑が検出され重要項目に関係し得る                  | `review_required`                |
| 期待言語が日本語なのに異常に非日本語化している                | `review_required`                |

### 8.5 Index gating

Quality status と index への投入可否を明確に分離する。

```text
accepted / manual_approved
  → primary text index
  → vector index
  → citation index
  → high-risk answer eligible

accepted_with_warnings
  → primary index
  → warning metadata attached
  → high-risk answer は warning 条件に従う

review_required
  → quarantine store
  → review queue
  → primary retrieval から除外

draft_visual
  → visual draft store
  → review queue
  → primary retrieval から除外
  → high-risk answer から除外

rejected
  → audit store
  → primary retrieval から除外
```

---

## 9. Parser / Provider Strategy

### 9.1 Docling-first

PDF / DOCX / PPTX / 画像系文書については、Docling を第一候補 provider とする。

理由は以下。

* 複数形式を統一的に扱える
* layout / reading order / table structure を持てる
* Markdown だけでなく JSON / structured representation を持てる
* RAG 向けの構造化前処理に向いている
* provider 出力を `ParsedDocument` に normalize しやすい

ただし、Docling の出力をそのまま正本にはしない。
DoclingDocument は provider output であり、内部正本は `ParsedDocument` とする。

### 9.2 Existing SpreadsheetParser stays

xlsx / csv については、現行のセル anchor 付き parser を維持する。

理由は以下。

* セル単位引用が製造現場 RAG に重要
* Excel 台帳では sheet / row / col / header の anchor が強い
* 汎用 parser で置換すると監査性が落ちる
* FR-MFG-002 相当の要件を維持する必要がある

ただし、出力 interface は `str` から `ParsedDocument` に揃える。

### 9.3 Native text extraction

クリーンな digital PDF では、OCR より native text extraction を優先する。

ただし、native text extraction は以下の品質確認を通す。

* 文字化けしていないか
* CID / CMap 問題がないか
* 日本語として自然か
* ページ上の視覚的テキスト量と抽出量が乖離していないか
* 表や段組の読み順が壊れていないか

疑わしい場合は OCR / Docling / VLM draft / review に fallback する。

### 9.4 OCR provider

OCR は Docling の内蔵機能としてではなく、provider として独立管理する。

候補は以下。

| Provider                    | 位置づけ                                               |
| --------------------------- | -------------------------------------------------- |
| PaddleOCR                   | local / self-hosted の日本語 OCR 候補                    |
| Google Document AI          | cloud OCR / layout / quality assessment 候補         |
| Azure Document Intelligence | cloud OCR / layout / table / document structure 候補 |
| Azure Vision OCR            | OCR 候補                                             |
| Tesseract-jpn               | fallback / low-cost local OCR 候補                   |
| RapidOCR                    | lightweight OCR 候補                                 |
| Textract                    | 日本語既定ではなく、対応言語・表/フォーム用途の補助候補                       |

既定 provider は Golden Eval Pack の結果で決める。

### 9.5 Textract の扱い

Textract は廃止しない。
ただし、日本語文書の既定 OCR からは外す。

使いどころは以下。

* 英語 / 欧州言語の帳票
* bbox / confidence を活用した補助比較
* TABLES / FORMS が強いケース
* 既存 AWS integration を活かせるケース

### 9.6 VLM provider

VLM は万能 parser ではなく、難物 fallback として使う。

対象は以下。

* 図面
* 手書き注記
* 印鑑・スタンプ
* 縦書き OCR が壊れる文書
* レイアウトが極端に複雑な文書
* OCR / Docling / native extraction が低信頼だったページ
* reviewer の判断補助

VLM 出力は原則 `draft_visual` とする。
人手承認なしに high-risk answer の引用根拠として使わない。

---

## 10. VLM Safety Policy

### 10.1 VLM は正本抽出器ではない

VLM は、画像・図面・手書き・視覚レイアウトの解釈に有効である。
一方で、存在しない文字列や意味をもっともらしく作るリスクがある。

したがって、本システムでは VLM を以下の用途に限定する。

| 用途                | 可否          |
| ----------------- | ----------- |
| 図面ページの概要説明        | 可           |
| reviewer への補助説明   | 可           |
| OCR 不能ページの triage | 可           |
| 手書き注記の候補読み取り      | 可、ただし draft |
| 高リスク回答の直接根拠       | 不可          |
| 人手承認後の引用根拠        | 可           |
| crop / bbox なしの引用 | 不可          |

### 10.2 VLM output requirements

VLM 出力には必ず以下を持たせる。

* 対象 page
* 対象 crop / bbox
* prompt version
* model name / model version
* temperature 等の generation config
* generated text
* confidence または self-rated uncertainty
* reviewer status
* 使用可否

例:

```json
{
  "kind": "visual_summary",
  "text": "図面右下の表題欄には部品名、図番、改訂番号が記載されている可能性がある。",
  "source_anchor": {
    "type": "page_crop",
    "page_no": 2,
    "bbox": [1600, 2500, 2400, 3400],
    "image_ref": "s3://..."
  },
  "provenance": {
    "provider": "vlm",
    "model": "claude_or_gemini_vision",
    "prompt_version": "visual_draft.v1"
  },
  "quality": {
    "status": "draft_visual",
    "reasons": ["vlm_output_unapproved"]
  }
}
```

### 10.3 VLM approval

VLM 出力は、次の条件を満たした場合のみ `manual_approved` に昇格できる。

* reviewer が対象 crop を確認した
* reviewer がテキストまたは構造化項目を承認した
* 必要に応じて修正した
* 承認者、承認時刻、承認対象 block が記録された
* 高リスク回答で使える引用 anchor が存在する

---

## 11. Chunking Strategy

### 11.1 SentenceChunker から structure-aware chunking へ移行する

現行の `SentenceChunker` は、文章中心の文書には有効である。
しかし、表、フォーム、図面、Excel、箇条書き、手順書では構造を壊す。

本 ADR では、チャンク化を `ParsedDocument` ベースに変更する。

```text
ParsedDocument
  ↓
Block-aware segmentation
  ↓
Structure-aware chunking
  ↓
Citation-preserving chunks
```

### 11.2 Chunk の基本方針

| Input block        | Chunk 方針                                |
| ------------------ | --------------------------------------- |
| `heading`          | 後続 block に context として付与                |
| `paragraph`        | 文境界を尊重して chunk                          |
| `list_item`        | list group を壊さず chunk                   |
| `table`            | 表全体または row group 単位で chunk              |
| `table_cell`       | セル anchor を保持                           |
| `form_field`       | key-value を壊さず chunk                    |
| `figure`           | caption + crop ref + visual summary     |
| `drawing`          | OCR text + visual draft + review status |
| `spreadsheet_cell` | sheet / row / col anchor を保持            |
| `visual_summary`   | draft として quarantine。承認後のみ通常 chunk 化    |

### 11.3 Chunk schema

```json
{
  "chunk_id": "chk_...",
  "document_id": "doc_...",
  "kind": "table_chunk",
  "text_for_embedding": "検査項目: 外観。基準: 傷なきこと。結果: OK。",
  "display_text": "| 検査項目 | 基準 | 結果 |\n|---|---|---|\n| 外観 | 傷なきこと | OK |",
  "source_blocks": ["b_1", "b_2", "b_3"],
  "source_anchors": [
    {
      "type": "page_bbox",
      "page_no": 3,
      "bbox": [120, 240, 1800, 920]
    }
  ],
  "quality": {
    "status": "accepted",
    "min_block_confidence": 0.91
  },
  "retrieval": {
    "eligible": true,
    "high_risk_citation_eligible": true
  }
}
```

### 11.4 High-risk answer eligibility

高リスク回答に使える chunk は以下に限定する。

* `accepted`
* `accepted_with_warnings` のうち policy 上許可されたもの
* `manual_approved`

以下は高リスク回答に使えない。

* `review_required`
* `rejected`
* `draft_visual`
* anchor がない chunk
* provider / model / version trace がない chunk
* 文字化け・低 OCR confidence の警告が未解決の chunk

---

## 12. Review / HITL Strategy

### 12.1 Review queue

`review_required` / `draft_visual` は `/reviews` に送る。

review item には以下を含める。

* document id
* page no
* page image
* crop / bbox
* extracted text
* provider result
* quality reasons
* route trace
* suggested action
* approve / edit / reject / escalate の選択肢

### 12.2 Review actions

| Action              | 結果                             |
| ------------------- | ------------------------------ |
| approve             | `manual_approved` に昇格          |
| edit_and_approve    | 修正テキストを正本として `manual_approved` |
| reject              | `rejected`                     |
| reprocess           | 別 provider / 別 config で再処理     |
| mark_as_non_content | ページを対象外扱い                      |
| escalate            | 専門 reviewer に回す                |

### 12.3 Review granularity

レビュー単位は文書全体ではなく、少なくとも page 単位、可能なら block 単位にする。

理由は、1 文書内に accepted page と review_required page が混在するためである。

---

## 13. Deployment / Runtime Policy

### 13.1 Heavy provider は opt-in

Docling、OCR、VLM、torch 系依存、クラウド OCR provider は opt-in provider として扱う。

理由は以下。

* minimalSpec のコスト制約
* Fargate image 肥大
* model weight 管理
* CVE surface の増加
* cold start / memory / CPU 影響
* provider ごとの課金管理
* 再現性管理

### 13.2 Async worker に載せる

重い処理は同期 path に入れない。

```text
Upload / ingestion request
  ↓
lightweight registration
  ↓
async ingestion worker
  ↓
provider execution
  ↓
quality gate
  ↓
index or review
```

同期 UX を守るため、以下を分ける。

| 処理                    | 実行場所                       |
| --------------------- | -------------------------- |
| file registration     | sync                       |
| hash / MIME detection | sync or lightweight worker |
| Docling parse         | async worker               |
| OCR                   | async worker               |
| VLM                   | async worker               |
| review queue creation | async worker               |
| index update          | async worker               |

### 13.3 Provider versioning

すべての provider 実行は version を記録する。

* parser provider name
* provider package version
* model version
* OCR language pack version
* prompt version
* config hash
* container image digest
* parser contract version
* chunking contract version

これにより、reindex / regression / audit を可能にする。

---

## 14. Golden Eval Pack

### 14.1 Phase 0 として必須化する

品質ゲートのしきい値を決める前に、代表文書セットを作る。

これを Golden Eval Pack とする。

対象例:

| Category          | 内容                 |
| ----------------- | ------------------ |
| digital_pdf_clean | デジタル日本語手順書         |
| digital_pdf_table | PDF 表つき帳票          |
| scanned_pdf_ja    | スキャン日本語帳票          |
| vertical_ja       | 縦書き帳票              |
| handwritten_note  | 手書き注記つき紙           |
| seal_stamp        | 印鑑・スタンプつき帳票        |
| broken_cmap       | 壊れ CMap / CID PDF  |
| drawing           | 図面 / CAD PDF       |
| spreadsheet       | Excel 台帳           |
| docx              | Word 手順書           |
| pptx              | PowerPoint 手順書     |
| mixed_pdf         | 本文・表・図面・スキャン混在 PDF |

### 14.2 評価指標

| Metric                    | 説明                      |
| ------------------------- | ----------------------- |
| false_accept_rate         | 低品質抽出を accepted にしてしまう率 |
| false_reject_rate         | 良品質抽出を review に落とす率     |
| CER / WER                 | OCR の文字誤り率 / 単語誤り率      |
| mojibake_detection_recall | 文字化け検知の再現率              |
| table_cell_accuracy       | 表セル内容の一致率               |
| table_structure_f1        | 行・列・ヘッダ構造の F1           |
| reading_order_accuracy    | 読み順の妥当性                 |
| citation_anchor_accuracy  | 引用 anchor の正確性          |
| page_route_accuracy       | page routing の妥当性       |
| review_reason_precision   | review reason が妥当か      |
| accepted_rate             | 自動 accepted 率           |
| review_required_rate      | review 行き率              |
| cost_per_page             | 1 ページあたりコスト             |
| latency_p50 / p95         | レイテンシ                   |
| provider_failure_rate     | provider ごとの失敗率         |

### 14.3 初期最適化目標

初期は自動処理率より false accept rate を重視する。

```text
Priority 1: false_accept_rate を下げる
Priority 2: citation_anchor_accuracy を上げる
Priority 3: table_structure_f1 を上げる
Priority 4: accepted_rate を上げる
Priority 5: cost_per_page を下げる
```

---

## 15. Phased Plan

### Phase 0 — Golden Eval Pack / Baseline

まず代表文書セットを作り、現行 pipeline の baseline を測る。

やること:

* 代表 PDF / Excel / Word / PPT / 図面を集める
* 現行 parser / OCR の結果を保存
* 低品質抽出の混入パターンを分類
* false accept を確認
* 品質 reason 候補を洗い出す

価値:

* しきい値を感覚ではなく実測で決められる
* Docling / OCR / VLM の評価軸ができる
* 後続 provider 導入の regression test になる

### Phase A — `ParsedDocument` + Quality Gate + Quarantine

最優先フェーズ。

やること:

* `ParsedDocument` contract を定義
* 現行 parser 出力を `ParsedDocument` に normalize
* 品質 dimension と reason code を実装
* `accepted` / `review_required` / `rejected` / `draft_visual` を導入
* `review_required` を通常 index から除外
* `/reviews` への連携 metadata を整備
* route_trace / provider_run を保存

価値:

* 低品質抽出が黙って RAG に混ざらなくなる
* 安全モデルの土台ができる
* parser を増やす前に汚染防止ができる

### Phase B — Docling-first Structured Parser

Docling を PDF / DOCX / PPTX / 画像系文書の第一候補 provider として導入する。

やること:

* Docling output を `ParsedDocument` に normalize
* Docling JSON / DoclingDocument を raw provider output として保存
* Markdown は `text_for_embedding` / display 用に生成
* table / heading / paragraph / figure / page / bbox を保持
* 現行 `SentenceChunker` を structure-aware chunker へ移行開始
* xlsx は現行 `SpreadsheetParser` 維持。ただし `ParsedDocument` 出力化

価値:

* 表、見出し、読み順、bbox が下流に流れる
* PDF 表の chunking / 引用品質が上がる
* Docling を中心にしつつ provider lock-in を避けられる

### Phase C — Japanese OCR Provider Selection

日本語 OCR provider を実測で選定する。

やること:

* PaddleOCR / Google Document AI / Azure Document Intelligence / Azure Vision OCR / Tesseract-jpn / RapidOCR を比較
* Textract は日本語既定から外し、補助 provider に降格
* 縦書き、手書き、印鑑、低解像度、斜めスキャンで評価
* provider ごとの cost / latency / accuracy を記録
* routing rule に OCR provider を組み込む

価値:

* スキャン日本語文書の自動処理率が上がる
* Textract 依存のリスクを下げられる
* 日本語製造文書に合わせた現実的な OCR 戦略になる

### Phase D — VLM Draft Fallback

難物だけ VLM に回す。

やること:

* drawing / handwriting / seal / vertical / low-confidence pages を VLM 対象にする
* VLM 出力は `draft_visual` として保存
* crop / bbox / prompt version / model version を保持
* `/reviews` で人手承認できるようにする
* 承認後のみ `manual_approved` として通常 index に入れる

価値:

* 図面・手書き・変則レイアウトの尻尾を回収できる
* VLM 幻覚を安全ゲートで抑えられる
* reviewer の作業効率が上がる

### Phase E — Reprocessing / Reindex

過去に取り込まれた文書を再評価する。

やること:

* 既存 document の parser_version / chunking_version を確認
* quality gate 未適用文書を再処理対象にする
* 低品質疑いの過去 chunk を quarantine する
* accepted chunk を新 schema で再 index する
* answer-service 側の retrieval filter を更新する

価値:

* 過去 index の汚染を減らせる
* 新旧 parser の差分を監査できる
* 安全モデルの一貫性が上がる

---

## 16. Rejected Alternatives

### A1. Docling-only にする

却下。

Docling は構造化パースの第一候補として強い。
しかし、日本語 OCR、縦書き、手書き、印鑑、図面理解、VLM 幻覚対策、品質ゲート、Excel セル anchor までは Docling 単体の責務にしない。

採用するのは **Docling-first** であり、**Docling-only** ではない。

### A2. Docling Markdown を正本にする

却下。

Markdown は読みやすく embedding に便利だが、bbox、confidence、provider trace、table cell、rowspan / colspan、review status などを十分に保持できない。

正本は `ParsedDocument` とする。

### A3. `parse(raw, content_type) -> str` を維持する

却下。

`str` だけでは、構造、引用 anchor、品質状態、provider trace を運べない。
RAG の引用品質と安全ゲートに必要な情報が失われる。

### A4. 全 PDF を OCR に回す

却下。

デジタル PDF の native text を捨てて OCR するのは、コスト、遅延、誤認識の面で不利である。
表構造や読み順も壊れやすい。

### A5. Textract を日本語 OCR の既定にする

却下。

Textract は日本語を公式サポート言語に含めていないため、日本語製造ドキュメントの既定 OCR としては採用しない。([AWS ドキュメント][5])

### A6. VLM を正本 parser にする

却下。

VLM は難物 fallback として有効だが、幻覚、視覚的曖昧さ、根拠不明な生成のリスクがある。
VLM 出力は draft とし、承認なしに高リスク回答へ使わない。

### A7. 最初からすべての provider を積む

却下。

minimalSpec、Fargate image、コスト、運用複雑性の観点で過剰である。
まず Phase A の品質ゲートと quarantine を作り、その後に自動処理率を上げる。

---

## 17. Consequences

### 17.1 Positive

* 低品質抽出が通常回答に混ざりにくくなる
* 表、見出し、ページ、bbox、セル anchor が下流に流れる
* 高リスク回答の引用品質が上がる
* Docling を中心にしながら provider lock-in を避けられる
* xlsx のセル単位引用を維持できる
* 日本語 OCR の provider 選定を現実的に進められる
* VLM を安全に fallback として使える
* reviewer に「何が怪しいか」を説明できる
* reindex / regression / audit が可能になる

### 17.2 Negative / Costs

* `ParsedDocument` contract の設計・実装が必要
* downstream chunker / indexer / answer-service の修正が必要
* quality gate のしきい値設計が必要
* provider version 管理が増える
* Docling / OCR / VLM 導入で worker image / memory / cost が増える
* review queue の運用設計が必要
* 過去 index の再評価が必要
* VLM / OCR の不確実性を扱うための UX が必要

### 17.3 Risks

| Risk                  | Mitigation                            |
| --------------------- | ------------------------------------- |
| Docling 依存が強くなりすぎる    | 正本を `ParsedDocument` にする              |
| OCR 精度が文書によりばらつく      | Golden Eval Pack と品質 gate             |
| review_required が多すぎる | Phase B/C/D で自動処理率を改善                 |
| VLM が創作する             | `draft_visual` + HITL + crop citation |
| コストが増える               | opt-in provider + 難物限定 routing        |
| 過去 index が汚染されたまま     | Phase E reprocessing                  |
| しきい値が厳しすぎる            | eval metrics に基づき調整                   |
| しきい値が緩すぎる             | false_accept_rate を最優先 metric にする     |

---

## 18. Operational Metrics

運用時は以下を継続的に見る。

### 18.1 Ingestion metrics

* documents processed
* pages processed
* provider distribution
* route distribution
* accepted rate
* accepted_with_warnings rate
* review_required rate
* rejected rate
* draft_visual rate
* manual_approved rate
* provider failure rate
* fallback rate
* average provider count per page

### 18.2 Quality metrics

* low OCR confidence pages
* mojibake suspected pages
* table structure low confidence pages
* drawing-like pages
* handwriting detected pages
* seal detected pages
* vertical text suspected pages
* empty extraction pages
* false accept estimate from review sampling
* review overturn rate

### 18.3 Cost / latency metrics

* cost per document
* cost per page
* OCR cost per page
* VLM cost per page
* Docling latency p50 / p95
* OCR latency p50 / p95
* VLM latency p50 / p95
* queue wait time
* worker memory usage
* worker failure / retry count

### 18.4 RAG quality metrics

* retrieval hit rate by document type
* citation exactness
* answer citation validity
* high-risk answer blocked due to invalid citation
* user feedback by source document type
* review-approved chunk usage

---

## 19. Security / Compliance Notes

* provider raw output は監査用に保存するが、保存期間・PII 取り扱いを別途定義する
* cloud OCR / VLM provider を使う場合は、顧客データの外部送信可否を tenant / environment policy で制御する
* no-train / data retention / region constraints は provider ごとに確認する
* provider config は tenant policy に従う
* `draft_visual` や `review_required` は通常回答に使えないよう retrieval filter で強制する
* high-risk answer では `accepted` / `manual_approved` かつ valid citation anchor を必須にする

---

## 20. Open Questions

1. **`ParsedDocument` v1 の最小 schema**
   Phase A で必須にする field と、Phase B 以降で追加する field をどこで分けるか。

2. **quality thresholds**
   `ocr_confidence_p10`、`mojibake_risk`、`table_structure_confidence` などの初期しきい値をどう置くか。

3. **Golden Eval Pack の所有者**
   評価文書の収集、正解データ作成、更新責任を誰が持つか。

4. **日本語 OCR の既定 provider**
   local-first にするか、cloud OCR を許容するか。tenant ごとの data policy とどう連動させるか。

5. **Docling worker の packaging**
   既存 ingestion worker に同居させるか、heavy parser worker として分けるか。

6. **review granularity**
   page 単位で始めるか、block 単位まで最初から対応するか。

7. **VLM provider**
   Claude vision / Gemini / その他をどう選ぶか。月次コスト上限と routing 閾値をどう定めるか。

8. **reindex strategy**
   既存取り込み済み文書を全件再処理するか、低品質疑いのものから段階的に再処理するか。

9. **answer-service retrieval filter**
   `review_required` / `draft_visual` を確実に除外する filter をどの層で強制するか。

10. **Excel セル anchor と Docling XLSX の関係**
    xlsx は現行 parser を正とするが、Docling XLSX 出力を補助的に使う余地を残すか。

---

## 21. Final Decision

本 ADR では、取り込み品質アーキテクチャを以下として決定する。

> **Docling-first, not Docling-only.**

Docling は、PDF / DOCX / PPTX / 画像系文書を構造化する第一候補 provider とする。
ただし、システムの正本は DoclingDocument ではなく、自社 `ParsedDocument` とする。

日本語 OCR は Docling 単体の責務にせず、PaddleOCR、Google Document AI、Azure Document Intelligence / Vision OCR、Tesseract-jpn、RapidOCR などを Golden Eval Pack で比較して選定する。

Textract は日本語 OCR の既定から外し、対応言語・表・フォーム用途の補助 provider とする。

VLM は難物 fallback として使うが、出力は `draft_visual` とし、人手承認なしに高リスク回答の根拠として使わない。

最初に作るべきものは、多エンジン対応でも VLM でもなく、以下である。

> **`ParsedDocument` + Quality Gate + Quarantine + Review Routing**

これにより、何が来ても完全に読めることは保証しない。
しかし、**読めなかったもの、怪しいもの、壊れたものが、黙って RAG の回答基盤に混入しないこと**を保証する。

[1]: https://docling-project.github.io/docling/usage/supported_formats/?utm_source=chatgpt.com "Supported formats - Docling"
[2]: https://arxiv.org/html/2408.09869v1?utm_source=chatgpt.com "Docling Technical Report"
[3]: https://arxiv.org/html/2408.09869v4?utm_source=chatgpt.com "Docling Technical Report"
[4]: https://docling-project.github.io/docling/getting_started/installation/?utm_source=chatgpt.com "Installation - Docling"
[5]: https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html?utm_source=chatgpt.com "Best Practices - Amazon Textract"
[6]: https://docs.cloud.google.com/document-ai/docs/processors-list?utm_source=chatgpt.com "Processor list | Document AI"
[7]: https://learn.microsoft.com/en-us/azure/ai-services/computer-vision/overview-ocr?utm_source=chatgpt.com "OCR - Optical Character Recognition - Foundry Tools"
[8]: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout?view=doc-intel-4.0.0&utm_source=chatgpt.com "What is the Document Intelligence layout model?"
[9]: https://paddlepaddle.github.io/PaddleOCR/main/en/index.html?utm_source=chatgpt.com "Home - PaddleOCR Documentation"

---

## 付録: 実装ステータス (2026-07-06, branch `018-ingestion-quality-architecture`)

`live` = 実コード + 決定的テスト（Tier A ゲート GREEN）で検証済み。`opt-in` = コード実装済みだが外部
依存（クラウド資格情報/重量級モデル）のため既定 OFF・遅延インポートで、ライブ検証は環境依存。`scaffold`
= 抽象化とフックは配置済みで既定 NoOp、将来の provider 差し込み口。

| ADR | 項目 | 状態 | 実装の所在 |
| --- | --- | --- | --- |
| §5/§7 | canonical `ParsedDocument`（DoclingDocument でも Markdown でもない） | live | `src/raku_rag/domain/parsed_document.py` |
| §9.1 | Docling 構造パーサ（PDF/DOCX/PPTX/HTML/画像） | live | `providers/docling_parser.py`（Docling 2.110 で実変換検証） |
| §7.6 | 表構造（ヘッダ検出つき）→ `Table`/`TableCell` | live | `docling_parser._table_from_item` |
| §7 | 図（`Figure`：page/bbox/caption） | live | `docling_parser._normalize_figures`（A2） |
| §8.2/§8.3 | 品質は「次元ベクトル」（§8.3 の16次元すべて） | live | `docling_parser._quality_from_confidence`（layout/ocr_p10/p50/overall, A3）+ `quality_detectors.document_quality_dimensions`（text_yield/empty_page_risk/mojibake_risk/language_consistency/reading_order_risk/table_structure_confidence/cell_anchor_coverage/visual_coverage/provider_error/**vertical_text_suspected** + 検出器系 drawing_like/handwriting/seal） |
| §13.3 | provider_version + config_hash + timestamps（再現/監査用） | live | `docling_parser._normalize`（A5） |
| §8.4 | 文書レベル ハードフェイル（低信頼/表構造/図面/手書き・印鑑/期待言語不一致） | live（検出器）/opt-in（vision） | `services/structured_ingestion.classify_parsed_document_quality`（A7）+ `services/quality_detectors.py`（table_structure_confidence・is_language_mismatch・drawing_like は実 stdlib；handwriting/seal は `VisualArtifactDetector` seam, 既定 NoOp・`RAKU_VISUAL_ARTIFACT_DETECTOR` で有効化） |
| Phase A | 抽出品質 contract + retrieval/high-risk ゲート | live | `services/ingestion_quality.py`, `retrieval.py`, `answer.py`, `manufacturing/safety/gate.py` |
| §4.2/§9.4 | OCR は独立 provider（Docling 内蔵 OCR は不使用） | live(RapidOCR)/opt-in(cloud) | `providers/ocr/pluggable.py`（RapidOCR 実 OCR 検証; Google/Azure は opt-in, A10） |
| §6.1/§6.2 | preflight（digital/scanned 判定）→ route_trace/page signals | live（判定）/ 部分（per-page 完全ルーティングは将来） | `docling_parser.preflight_pdf_pages` / `_apply_preflight`（A6） |
| §P2 | raw provider 出力の保管（再現/監査） | live(fs)/opt-in(s3) | `services/raw_sink.py`（A4） |
| §12.1 | レビューキュー一覧（Postgres 効率クエリ + in-mem 射影）+ 各項目に page_no/anchor(bbox)/抽出テキスト/quality reasons/suggested_action | live | `persistence/postgres.list_extraction_review_chunks`, `ingestion_quality.extraction_review_queue`/`ExtractionReviewItem`（A9）, web に page/snippet/推奨アクション表示 |
| Phase E | reindex 時の品質再評価（低品質を quarantine） | live | `services/reindex.py`（A12） |
| §10/Phase D | VLM draft fallback → `draft_visual`（HITL 承認前提） | opt-in | `providers/vlm_draft.py`：`BedrockVlmDraftProvider`（実 Claude vision, `RAKU_VLM_DRAFT_PROVIDER=bedrock`）+ NoOp 既定 |
| §8.4 | 手書き/印鑑/図面の vision 検出器 | opt-in | `quality_detectors.BedrockVisualArtifactDetector`（実 Claude vision, `RAKU_VISUAL_ARTIFACT_DETECTOR=bedrock`）+ NoOp 既定 |
| §12.2/§10.3 | reviewer アクション（approve/edit/reject/reprocess/mark_non_content/escalate）+ `manual_approved` 昇格 | live | `services/review_actions.py`, `POST /internal/reviews/extraction/actions`, `apps/api ReviewsController`, `apps/web /reviews/extraction` |
| §18 | 運用メトリクス（status別レート + reason別カウント + quarantine率） | live | `ingestion_quality.extraction_quality_stats`, `GET /internal/reviews/extraction/metrics` |
| §13.2/§9.1 | worker が PDF を Docling 経路へ | live | `IngestionExecutor(structured_pdf=…)`（構造化ON時） |
| 配線 | 構造化取り込みへのフラグ切替 | live | `RAKU_STRUCTURED_INGEST` → `app.py`/`production.py`（A1） |

**閾値チューニング機構（§OQ#2）は実装済み**: §8.4 の全ゲート閾値（mojibake/control-char 比率・空抽出バイト下限・
overall/layout/table-structure 信頼度）は `services/quality_thresholds.py` の `RAKU_QT_*` env で**呼び出し時に再読込**され、
デプロイや eval sweep がコード変更なしで再調整できる（既定は safety-first で不変）。Golden Eval Pack（`eval/fixtures/
ingestion_quality_golden.json`）は 13 ケース（clean×4 / accepted_with_warnings×1 / blocking×8：mojibake・高置換率・
制御文字混入・CID×2・空抽出 PDF/Office×2・軽微化け）に拡充し、false_accept_rate==0 を保ったまま網羅を広げた。

**vision/VLM 系も実アダプタを実装済み（opt-in・§19 egress-gated・オフライン mock 検証）**: 手書き/印鑑/図面検出は
`BedrockVisualArtifactDetector`、難ページの draft OCR は `BedrockVlmDraftProvider`（いずれも既存の `build_bedrock_vision_invoker`
= 実 Claude vision を実バックエンドに、`RAKU_ALLOW_CLOUD_EGRESS` + boto3 が揃うまで unavailable）。クラウド OCR は
Google DocAI / Azure DI が既に実装済み。全て注入 invoker で request/parse をオフライン検証（`tests/unit/test_bedrock_vision_adapters.py`）。

**真に残るのは「外部リソースでのライブ検証」だけ（コードは完了）**: (1) §OQ#2 の**代表文書での実測閾値の確定**
（実顧客文書 + 人手ラベリングが必要。チューニング機構・synthetic seed・false_accept ゲートは実装済み）、(2)(3) 上記
vision/VLM/クラウド OCR アダプタの**本番資格情報でのライブ実行確認**（アダプタ・egress ゲート・mock テストは実装済み；
Bedrock/Google/Azure の creds を与えれば即動作）。これらは ADR 自身が opt-in（§13.1）/ Open Question（§20）として扱う
項目。それ以外の設計項目は実装・検証済み（Tier A gate 1883 GREEN + 実 Docling + 実 Postgres + NestJS e2e + web build）。
