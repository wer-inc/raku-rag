# Research: AI Phone RAG Contact Center

**Feature**: `022-ai-phone-rag`

**Date**: 2026-06-28

## Decision 1: MVP は live 電話基盤ではなく deterministic call simulator から始める

**Decision**: MVP の inner loop は `CallSimulator` を正式 provider として扱い、テキスト発話イベント、DTMF、barge-in、provider failure を再現できるようにする。live SIP/PBX/Amazon Connect/Twilio 等は後続 adapter として実装する。

**Rationale**:

- `scripts/gate.sh a` に network/cloud/telephony/billed provider を入れられない。
- 電話AIの安全性は、まず会話状態・RAG根拠・handoff 判定・履歴保存で検証できる。
- live telephony は運用環境、番号、録音、転送、課金が絡むため human approval が必要。

**Alternatives considered**:

- いきなり Amazon Connect 等に寄せる: 本番には近いが、開発ループとテストが重くなるため却下。
- WebRTC ブラウザ通話から始める: デモ性は高いが、コールセンター転送/ACD を抽象化しにくいため後続扱い。

## Decision 2: ASR/TTS は provider interface とし、MVP は transcript-in / text-out の deterministic 実装

**Decision**: `AsrProvider` は音声/segment から transcript events を返す契約、`TtsProvider` は応答テキストから再生可能 reference を返す契約にする。MVP では ASR は入力テキストを信頼度付き segment として返し、TTS はテキストと擬似 audio ref を返す。

**Rationale**:

- 会話制御、handoff、RAG、安全ゲートのテストを音声モデル品質から分離できる。
- 後で real ASR/TTS を追加しても、orchestrator と call history の契約を維持できる。
- PII redaction は transcript レイヤで先に pin できる。

**Alternatives considered**:

- 音声ファイルベースの ASR を最初から必須にする: テストデータと依存が重く、Tier A に不適。
- TTS を実 audio 必須にする: MVP の価値は会話制御と根拠付き応答なので後続に回す。

## Decision 3: RAG は既存 `AnswerService` / retrieval / citation / ACL を再利用する

**Decision**: 電話用の別 vector store や別 retrieval path は作らない。電話 orchestrator は既存の tenant-scoped answer/search サービスを呼び、結果の answer/citations/safety status を turn log に保存する。

**Rationale**:

- 既存 001/002 の tenant isolation、ACL pre-filter、groundedness、citation、deletion、provider policy を再利用できる。
- 電話向けに独自検索を作ると、ACL 漏洩や deleted content reappearance の回帰面が増える。
- ナレッジ管理は既存の datasource/approval/review flow と整合させるべき。

**Alternatives considered**:

- 電話専用 KB を別管理する: シンプルに見えるが、ナレッジ鮮度・承認・ACL が二重管理になるため却下。

## Decision 4: Orchestrator は「答える」より「状態遷移を決める」責務にする

**Decision**: 電話 orchestrator は各 turn で、`ask_clarification` / `answer_with_citations` / `handoff` / `fallback` / `end_call` のいずれかの action を決める。LLM応答生成はその action の一部として呼び出すが、状態遷移の最終判断は policy/scenario/safety rules で閉じる。

**Rationale**:

- 電話では沈黙、聞き返しループ、勝手な約束、転送拒否が重大な UX/安全事故になる。
- 「人につないで」は LLMに判断させず、hard rule として扱う必要がある。
- scenario required slots と handoff rules を明示的に評価できる。

**Alternatives considered**:

- LLMに全会話制御を委ねる: 自然さは出るが、転送や禁止応答が不安定になるため却下。

## Decision 5: HandoffPackage は first-class entity とする

**Decision**: 転送は単なる status ではなく、`HandoffPackage` として永続化し、operator UI/API に渡す。必須項目は summary、transcript、caller/customer identifiers、intent、confirmed slots、citations、sentiment、reason、destination、recommended next action。

**Rationale**:

- 顧客が同じ説明を繰り返す体験を避ける。
- 転送理由とAIの判断根拠を QA/監査/改善に使える。
- 転送失敗、放棄、キュー待ちなどを KPI として測れる。

**Alternatives considered**:

- transcript だけ渡す: オペレーターの読む負担が大きく、CX改善にならないため却下。

## Decision 6: Scenario は draft/review/published/archived + immutable version で管理する

**Decision**: `CallScenario` は編集可能な logical record、`ScenarioVersion` は immutable version とする。公開済み version は直接変更せず、新 version を承認・公開する。各 call は scenario version ID を記録する。

**Rationale**:

- 過去通話がどの会話ルールで応答されたか追跡できる。
- 問題発生時に前 version へ戻しやすい。
- 既存の AI draft / document approval の安全思想と整合する。

**Alternatives considered**:

- scenario JSON を直接上書き: 実装は速いが監査・rollback・QA に弱いため却下。

## Decision 7: Recording/transcript retention は tenant policy として明示する

**Decision**: call audio、transcript、summary、citations、handoff package、exports は retention class を持つ。録音告知を流したかどうかも call metadata に保存する。MVP では録音保存は optional とし、transcript 保存を中心に設計する。

**Rationale**:

- 電話履歴には個人情報が含まれる可能性が高い。
- 録音保存は法務・運用・ストレージ・アクセス制御に影響する。
- MVP では transcript と audit を先に安全に扱う方が現実的。

**Alternatives considered**:

- 全通話を常時録音保存: コンプライアンスとコストが重く、初期MVPには不適。

## Decision 8: Phone QA と existing improvement queue を接続する

**Decision**: `QualityEvaluation` で hallucination/compliance/tone/handoff appropriateness を記録し、誤回答やナレッジ不足は既存のナレッジ改善キューに流す。

**Rationale**:

- 電話AIは運用改善ループが価値の中心。
- 既存の feedback/improvement/audit 機構とつながると、RAG改善が分断されない。

**Alternatives considered**:

- 電話QAを独立DBにする: 分析は楽に見えるが、ナレッジ改善と分離するため却下。

## Decision 9: MVP の対象問い合わせを限定する

**Decision**: MVP は business hours、FAQ、pricing/plan、reservation/order status、document request、department routing に限定する。refund/legal/medical/financial/complex identity/card payment は transfer-only または out-of-scope。

**Rationale**:

- 初期の安全性とデモ成功率を高める。
- 高リスク判断はRAG精度だけでは足りず、業務権限・本人確認・監査が必要。

**Alternatives considered**:

- 最初から全問い合わせ対応: 価値は大きいが、安全境界が広すぎるため却下。

## Resolved MVP Boundaries

1. Operator console は product MVP では既存 web app 内の handoff queue/detail stub から始める。外部 CCaaS/CRM payload 連携は post-MVP adapter。
2. 録音保存は MVP 必須にしない。Product MVP は transcript-first とし、録音は tenant recording policy が有効な場合のみ保存・表示する。
3. CRM/注文/予約 lookup は deterministic stub または既存 demo data に限定する。Live業務API連携は post-MVP。
4. 本人確認は complex identity verification を MVP 外にする。本人確認が必要な問い合わせは、限定 scripted hints で足りない場合に handoff する。

## Remaining Open Questions

1. ~~最初の production telephony target は Amazon Connect / Twilio / SIP/PBX / existing customer PBX のどれか。~~
   **RESOLVED (2026-07-02): Amazon Connect** — 決定の根拠と実装は `specs/024-phone-live-telephony/`
   (research.md Decision 1)。AWS完結の請求/IAM/監視一元化、キュー+CCP による人間転送の標準装備、
   Lex V2 ja-JP / Polly のASR/TTS内蔵、050 DID の低ランニングコストが決め手。
2. 最初の production CRM/order/reservation integration target はどの顧客・業務APIか。
