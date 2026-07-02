# 業界依存の棚卸し — config化監査とロードマップ(★V2, 2026-07-02)

導入業界の多様化に向け、「コード変更なしでどこまでテナント/業界別に振る舞いを変えられるか」を
監査した結果。判定は3段階: **A=テナントが画面/APIで変更可** / **B=デプロイ設定(env/context)で
変更可** / **C=ハードコード(要改修)**。

## 判定一覧

| 領域 | 実体 | 判定 | 備考 |
|---|---|---|---|
| 回答プロファイル(閾値・top_k・最少根拠数) | QueryProfile / retrieval profiles API | **A** | テナント別に調整可 |
| チャットボットのシナリオ・クイックリプライ | chat scenarios(テナント編集API) | **A** | 業界別FAQ導線はここで対応 |
| 電話のシナリオ・スロット・転送条件 | phone scenarios(承認フロー付き編集API) | **A** | faq-basic は初期値にすぎない |
| データソースの信頼/承認ポリシー | config.approval_policy(サーバ側強制) | **A** | trusted→approved 等 |
| チャットボットの会話能力段階(L0-L4) | tenant authority repository | **A** | テナント別ダイヤル |
| プロバイダ(LLM/埋め込み/OCR/ガードレール) | deploy inputs / CDK context | **B** | answer_llm=bedrock\|openai\|gemini 等 |
| OCR品質ゲート閾値 | RAKU_OCR_CONFIDENCE_REVIEW_THRESHOLD | **B** | ★V1 で追加 |
| 電話データ保持・エクスポート | RAKU_PHONE_*_RETENTION_DAYS / EXPORT_ENABLED | **B** | テナント別化は将来課題 |
| **高リスク判定キーワード**(安全/設備/危険意図) | `manufacturing/safety/classifier.py` の固定セット | **C** | 製造業前提。医療・金融等では別語彙が必要 |
| **チャット転送トリガ語**(担当者/オペレーター等) | `chatbot/service.py` 固定文言 | **C** | 文言もロジックも固定 |
| **電話の意図分類キーワード**(返金/解約→refund等) | `phone/orchestrator.py` 固定マップ | **C** | コールセンター業務語彙が固定 |
| **抽出型回答のマーカー語**(原因/対策/手順…) | `providers/llms.py` 固定リスト | **C** | 実LLM運用では影響小(生成型が主) |
| 定型応答文言(転送アナウンス・免責等) | 各サービスの固定文字列 | **C** | ブランドトーン変更ができない |

## 結論

**骨格(シナリオ・プロファイル・ポリシー・プロバイダ)は既に config 駆動**で、業界展開の
土台はある。残る C は「**語彙**」と「**文言**」に集中している — つまり必要なのは汎用の
*テナント別ルール表*が1つであり、個別改修の積み上げではない。

## 提案: tenant_lexicon(テナント別語彙・文言レジストリ)

RLS付きテーブル1枚 + 読み出しシームで C 群を一括吸収する:

```
tenant_lexicon(tenant_id, namespace, key, values jsonb)
  例: (t1, safety.high_risk_keywords, electrocution, ["感電","活線",...])
      (t1, chat.handoff_triggers, default, ["担当者","オペレーター","人間"])
      (t1, phone.intents, refund_cancellation, ["返金","解約",...])
      (t1, messages.handoff_announce, default, "担当者におつなぎします。")
```

- 各分類器/サービスは「**デフォルト(現行値)⊕ テナント上書き**」で解決(未設定テナントは現状維持
  = 後方互換)。**安全側不変条件**: safety キーワードは*追加のみ許可*(削除・縮小は不可 —
  高リスク検知を弱める設定をテナナントに渡さない)。変更は監査ログに記録。
- 実装順: ①safety.high_risk_keywords(追加のみ) → ②chat/phone トリガ語 → ③文言。
  ①が最優先(業界追加の実需+安全設計の見せ場)。

## 実装状況

- [ ] 提案テーブル + 解決シーム(未着手 — 次スプリント候補)
- [x] 本監査ドキュメント
