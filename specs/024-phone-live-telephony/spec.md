# Feature Specification: Live Telephony Adapter (Amazon Connect)

**Feature Branch**: `024-phone-live-telephony`

**Created**: 2026-07-02

**Status**: In progress

**Input**: 022-ai-phone-rag P1 (deterministic phone layer, shipped on develop / stg) を実電話に接続する。
022 research.md Open Question #1 は **Amazon Connect** に決定(本 feature の research.md 参照)。

## Scope

**In scope (this slice)**:

- **US-L1: 実番号への着信で AI が応答する** — PSTN 発信者が Connect の日本番号(050 DID)に発信すると、
  Contact Flow + Lex(ja-JP ASR)+ アダプタ Lambda 経由で既存 `/internal/phone/*` が呼ばれ、
  根拠付き回答が Polly 音声で返る。022 の会話制御・安全ゲート・引用・赤入れは**変更しない**。
- **US-L2: 実通話からの人間転送** — `ai_action=handoff` で Connect キューへ転送し、オペレータが
  CCP で受電する。HandoffPackage の参照URLを contact attribute として渡す。
- **US-L3: ブラウザ音声デモ** — 課金ゼロの音声体験(Web Speech API)。`/phone` シミュレータに
  音声モード(マイク入力→既存API→読み上げ、合成中の割り込み停止)。
- **音声向け回答整形** — 読み上げ可能な `speech_text`(markdown/箇条書き除去・短文化・続き案内)を
  turn payload に追加。UI 用 `ai_response_text` は不変。

**Out of scope**: 発信(アウトバウンド)、0120/0800、録音保存、Connect Cases/Customer Profiles、
複数番号ルーティング UI、Bedrock 音声モデル、多言語。

## Functional Requirements

- **FR-L01**: アダプタは Connect Contact Flow の Lambda 呼出しイベントを受け、`call_start` / `turn` を
  既存 internal phone API に中継しなければならない(MUST)。会話の状態遷移判断をアダプタ内に
  持ち込んではならない(MUST NOT — Decision 4 の維持)。
- **FR-L02**: 着信番号(DID)→ {tenant_id, service user/groups, collection_id, scenario_id} の解決は
  設定(SSM)で行い、未登録 DID はفail-closed(定型案内+切断)としなければならない(MUST)。
- **FR-L03**: アダプタが合成する principal は電話チャネル専用のサービスロール(`phone_gateway`)を
  持ち、phone の simulate/turn のみに有効で、通話履歴閲覧・シナリオ管理には使えない(MUST)。
- **FR-L04**: 発信者番号は Lambda 内でマスクしてから API へ渡す(raw E.164 をログ・API・属性に
  出さない)(MUST)。
- **FR-L05**: turn 応答の `speech_text` は読み上げ短文(目安 ≤3文/160字)+途中打切り時の続き案内を
  含む(MUST)。`answer_with_citations` の音声には文書IDの読み上げを含めない(引用は画面/履歴で確認)。
- **FR-L06**: `ai_action=handoff` は Connect キュー転送に、`end_call` は切断に、`fallback` /
  `ask_clarification` は再入力ループにマップする(MUST)。API 到達不能・タイムアウト時は無音に
  せず定型フォールバック→転送に倒す(MUST — SC-008 の実電話版)。
- **FR-L07**: 録音はデフォルト無効。開示プロンプトは flow 設定で制御し、再生有無を contact
  attribute → call metadata に反映する(SHOULD)。
- **FR-L08**: CDK は `phoneTelephony=connect` コンテキストが明示されたときのみ電話リソースを
  合成する(MUST)。デフォルト OFF で既存 stg デプロイの挙動を変えない。
- **FR-L09**: ブラウザ音声モードは既存 simulate/turn API のみを使い、認識/合成はブラウザ内で完結
  する(MUST — 新たなクラウド課金なし)。非対応ブラウザではトグルを無効表示する。

## Success Criteria

- **SC-L1**: 携帯から 050 番号に発信 → 挨拶 → FAQ 質問 → 根拠に基づく音声回答(体感 ≤4秒/ターン)。
- **SC-L2**: 「人につないで」→ 1ターン以内にキュー転送 → CCP で受電 → `/phone` 転送キューに
  HandoffPackage が表示される。
- **SC-L3**: 未登録番号への着信・API 障害注入で、無音にならず定型案内で終了する。
- **SC-L4**: フラグ OFF の stg デプロイは既存全ゲート GREEN のまま(挙動不変)。
- **SC-L5**: ブラウザ音声モードで マイク→音声回答→割り込み停止 が Chrome で動作する。

## Assumptions

- 番号取得は runbook(`docs/phone/connect-setup-runbook.md`)に従い人間が実施(法人書類・サポートケース)。
- Connect インスタンス作成・番号紐付け・Lex/Flow 取込みはコンソール手作業(one-time)。コードは
  取込み可能なアーティファクト(`infra/connect/`)と CDK(Lambda 等)を提供する。
- 実通話・課金リソースの有効化は human-gated(ユーザー承認済み: 2026-07-02)。
