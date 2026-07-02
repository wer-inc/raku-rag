# Implementation Plan: Live Telephony Adapter (Amazon Connect)

**Branch**: `024-phone-live-telephony` | **Date**: 2026-07-02 | **Spec**: [spec.md](spec.md)

## Summary

022 の決定論電話レイヤを実電話に接続する。判断はすべて既存 orchestrator に残し、追加するのは
「翻訳層」だけ: Connect Contact Flow(ループ制御)+ 最小 Lex(ja-JP ASR)+ stdlib Lambda
(イベント→ `/internal/phone/*` 中継)+ 音声整形(`speech_text`)+ ブラウザ音声デモ。
実課金リソース(インスタンス・番号)は runbook による人間手続きで、コードはフラグ OFF で無害に同梱する。

## Technical Context

**Path**: PSTN → Connect(number/flow/queue)→ Lex V2 ja-JP(ASR)→ Lambda(python3.12, stdlib,
VPC private subnets)→ answer-service internal ALB `/internal/phone/*`(X-Internal-Auth)→ 022 layer。
TTS は flow の Polly。転送は Connect queue + CCP。

**New surfaces**: `src/raku_rag/phone/voice.py`, `infra/connect/`(lambda + flow JSON + README),
CDK `phoneTelephony` context(default off), `/phone` 音声モード(Web Speech API)。

**Constraints**: Tier A は stdlib/offline のまま(アダプタは fixture テスト)。フラグ OFF で
stg デプロイの挙動不変。実通話の有効化は human-gated(承認済み 2026-07-02、番号は申請中)。

## Constitution Check

- **I/II Groundedness・Traceability**: PASS — 回答系は 022 経路を再利用。`speech_text` は表現のみで
  引用・監査は不変。通話は provider_call_id=ContactId で追跡。
- **III Security**: PASS — 内部境界(X-Internal-Auth)再利用、`phone_gateway` 最小ロール、
  DID 未登録 fail-closed、raw 発信者番号は Lambda 内でマスク。
- **IV Pluggable**: PASS — Connect は TelephonyProvider 契約の外側の「チャネルアダプタ」。
  022 のプロバイダ差し込み口・決定論プロバイダは不変。
- **V/VI Evaluation・Observability**: PASS — fixture テスト+障害注入 SC-L3。contact flow logs +
  既存 correlation_id。
- **VII API First**: PASS — 公開 API 変更なし(turn payload への `speech_text` 追加は後方互換)。
- **VIII Lifecycle**: PASS — 録音 OFF/transcript-first、既存 retention 方針のまま。

## Risk Register(実電話特有)

| Risk | Mitigation |
|---|---|
| 番号審査の遅延(最長リードタイム) | runbook §2 を初日に起票。コードは全て番号非依存で先行 |
| ターン遅延で会話が不自然 | 抽出型LLMで ~1-2s 実測。flow に「お調べします」プロンプト、speech_text 短文化 |
| Lambda→API 障害で無音 | flow のエラー分岐で定型案内→キュー転送(SC-L3) |
| アダプタへの過剰権限 | `phone_gateway` は simulate/turn のみ(security テストで固定) |
| stg 請求増 | フラグ OFF 同梱。ON 時も Lambda+SSM のみ(番号 ¥450/月+従量) |
