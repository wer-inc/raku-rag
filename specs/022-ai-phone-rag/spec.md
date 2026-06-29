# Feature Specification: AI Phone RAG Contact Center

**Feature Branch**: `022-ai-phone-rag`

**Created**: 2026-06-28

**Status**: Draft

**Input**: User description from `/workspace/raku-rag/goal.md`: "社内ナレッジやFAQをRAGで参照しながら、顧客からの電話に自然な会話で応答し、必要に応じて人間のオペレーターへ引き継ぎ、応対履歴・回答根拠・シナリオ・品質を管理できるAI電話対応プラットフォーム。"

## Scope Slices

- **P1 technical demo**: US1 through US3. Demonstrates deterministic phone simulation, grounded answers, safe human handoff, and scenario operations. It may persist only the minimum call/turn/handoff records required for traceability.
- **Product MVP from `goal.md`**: P1 technical demo plus minimum US4 and US5 capabilities: searchable redacted call history, QA review creation, and a basic KPI dashboard. This is the first customer-facing MVP acceptance slice.
- **Post-MVP**: live telephony adapters, deep CCaaS/CRM/PBX integration, complex identity verification, audio recording as a default, outbound calls, multi-language, A/B testing, and advanced VOC analytics.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - AIが電話を受け、根拠付きで回答する (Priority: P1)

顧客が電話をかけると、AIが自然な音声で応答し、FAQ・マニュアル・規約などの承認済みナレッジを検索して、根拠がある範囲だけを説明する。根拠が弱い、古い、または権限外の場合は断定せず、確認質問または人間転送に切り替える。

**Why this priority**: 電話対応プラットフォームの最小価値は、顧客の問い合わせを音声で受け、根拠付きで安全に回答できること。

**Independent Test**: テレフォニーをシミュレートした inbound call API に対し、営業時間・FAQ・料金案内などの限定問い合わせを発話テキストで投入し、AI応答、TTS用テキスト、参照ナレッジID、回答不能時の転送判定が返ることを確認する。

**Acceptance Scenarios**:

1. **Given** 承認済みFAQに営業時間の根拠がある, **When** 顧客が「今日の営業時間は？」と電話で尋ねる, **Then** AIは営業時間を回答し、応答ログに `document_id` / `chunk_id` / `version` / `retrieval_score` を残す。
2. **Given** 該当するナレッジがない, **When** 顧客が未登録の返金条件を尋ねる, **Then** AIは断定せず「確認して担当者へおつなぎします」と案内し、転送候補を作る。
3. **Given** 顧客がAI発話中に話し始めた, **When** 割り込み発話が検知される, **Then** AIの発話は停止され、顧客発話の認識を優先する。

---

### User Story 2 - 人間オペレーターへ適切に引き継ぐ (Priority: P1)

顧客が「人につないで」と言った場合や、根拠不足・本人確認が必要だがMVPで扱えない場合・クレーム兆候・高リスク問い合わせが検出された場合、AIは無理に完結させず、適切な部署・キュー・オペレーターへ転送する。転送時には会話要約、転送理由、確認済み項目、参照根拠をオペレーターに渡す。

**Why this priority**: AI電話対応では、AIで抱え込まないことが安全性と顧客体験の核心。転送がないAI応答は本番運用に出せない。

**Independent Test**: 顧客の転送希望、根拠不足、怒り表現、本人確認が必要だがMVPで扱えない会話を投入し、handoff package が生成され、転送先キューと理由が記録されることを確認する。

**Acceptance Scenarios**:

1. **Given** 顧客が「オペレーターに代わって」と言う, **When** AIが発話を解析する, **Then** AIは拒否せず転送処理に入り、転送理由 `customer_requested_human` を記録する。
2. **Given** RAG検索結果が信頼度しきい値未満, **When** AIが回答候補を生成しようとする, **Then** AIは断定回答を出さず、転送理由 `insufficient_evidence` を作成する。
3. **Given** 転送が発生した, **When** オペレーター画面が開かれる, **Then** 会話要約、全文、顧客ID/電話番号、確認済み項目、参照ナレッジ、感情状態、推奨次アクションが表示される。

---

### User Story 3 - 管理者がナレッジとシナリオを運用する (Priority: P1)

管理者または業務責任者は、FAQ・マニュアル・規約などのナレッジを更新し、問い合わせ種別ごとの会話シナリオを作成・レビュー依頼・承認・公開できる。公開前に想定会話でプレビューし、問題があれば前バージョンへ戻せる。

**Why this priority**: 電話AIはモデルだけでは運用できない。業務担当者がナレッジと会話ルールを更新できなければ、実運用で陳腐化する。

**Independent Test**: 管理者がFAQを追加し、シナリオに必須確認項目と転送条件を設定し、テスト会話でAI応答と転送条件を確認した後、公開できることを確認する。

**Acceptance Scenarios**:

1. **Given** 新しいFAQがアップロードされた, **When** 管理者が承認して公開する, **Then** 次回以降の電話応答でそのFAQが検索対象になり、回答ログに新しいバージョンが残る。
2. **Given** 請求問い合わせシナリオがある, **When** 管理者が「契約番号確認」を必須項目に設定する, **Then** AIは請求説明前に契約番号を確認する。
3. **Given** シナリオ変更が公開済み, **When** 問題が発見される, **Then** 管理者は前バージョンを再公開でき、過去通話は当時のシナリオバージョンで追跡できる。

---

### User Story 4 - 応対履歴と品質を追跡する (Priority: P2)

スーパーバイザーは、通話一覧、録音、文字起こし、AI応答、参照根拠、転送理由、結果分類、品質評価を確認し、誤回答やナレッジ不足を改善キューへ送れる。

**Why this priority**: 電話対応は監査・教育・品質改善が不可欠。履歴と評価がなければ、誤回答や転送過多を改善できない。

**Independent Test**: 完了済み通話を検索し、詳細画面で transcript、AI応答、根拠、転送、品質評価を確認し、改善指示を登録できることを確認する。

**Acceptance Scenarios**:

1. **Given** 通話が完了している, **When** スーパーバイザーが通話IDを開く, **Then** 文字起こし、要約、AI応答、参照根拠、転送ログが表示され、録音が有効な通話では録音URLも権限付きで表示される。
2. **Given** スーパーバイザーが誤回答を発見した, **When** 品質評価で `hallucination_detected=true` を登録する, **Then** ナレッジ改善キューに修正候補が作られる。

---

### User Story 5 - 運用KPIを可視化する (Priority: P2)

運用責任者は、着信数、AI完結率、転送率、転送理由、未解決率、よくある問い合わせ、ナレッジ不足、応答遅延、CSATなどをダッシュボードで確認できる。

**Why this priority**: AI電話対応の価値はAI精度だけでなく、コールセンター運用KPIで測る必要がある。

**Independent Test**: テスト通話を複数投入し、ダッシュボードがAI完結率、転送率、主要転送理由、平均応答遅延を集計することを確認する。

**Acceptance Scenarios**:

1. **Given** 複数のAI完結通話と転送通話がある, **When** ダッシュボードを開く, **Then** AI完結率と転送率が正しく表示される。
2. **Given** `insufficient_evidence` 転送が増えている, **When** 転送理由分析を見る, **Then** ナレッジ不足として該当問い合わせが上位表示される。

---

### Edge Cases

- 顧客が「人につないで」と繰り返す場合、AIは説得や引き止めをせず転送する。
- ASR信頼度が低い発話が続く場合、聞き返し回数を制限し、一定回数で人間へ転送する。
- 顧客が怒り、不安、強い不満を示す場合、AIはトーンを変え、必要に応じて優先転送する。
- RAG検索結果が古い版、停止中、承認待ち、権限外のみの場合、AIは正式回答に使わない。
- 営業時間外、休日、混雑時、障害発生時は通常シナリオではなく、事前に設定された案内または転送先を使う。
- カード番号、認証情報、機微情報を顧客が発話した場合、transcript/log/trace ではマスキングする。
- テレフォニー、ASR、TTS、LLM、RAG、CRM のいずれかが失敗した場合、ユーザーに無音や未完了を返さず、フォールバック案内または人間転送に倒す。
- 同一顧客が短時間に再入電した場合、前回通話の要約をオペレーターまたはAIのコンテキストとして参照できる。ただしACLと保持期間を守る。
- AIが業務処理権限を持たない操作を求められた場合、回答ではなく転送またはチケット作成にする。

## Requirements *(mandatory)*

### Functional Requirements

#### 電話・音声対応

- **FR-001**: System MUST accept inbound calls through a pluggable telephony adapter.
- **FR-002**: System MUST create a unique `call_id` for every inbound call before conversation processing starts.
- **FR-003**: System MUST support streaming or near-real-time ASR through a pluggable ASR provider.
- **FR-004**: System MUST produce TTS-ready response text and optionally synthesized audio through a pluggable TTS provider.
- **FR-005**: System MUST support barge-in: when the customer speaks during AI speech, AI speech is interrupted and customer input is processed.
- **FR-006**: System MUST support DTMF input for menus, identity hints, and fallback flows.
- **FR-007**: System MUST support hold/resume states and configured waiting messages.
- **FR-008**: System MUST route calls by business hours, holidays, incident banners, and queue availability.

#### RAG回答・会話制御

- **FR-009**: System MUST reuse the existing tenant-scoped RAG retrieval, groundedness, citation, deletion, and ACL behavior instead of creating a separate knowledge path.
- **FR-010**: System MUST answer only when retrieved evidence is sufficient, current, permitted, and traceable.
- **FR-011**: System MUST log every AI answer with `source_id`, `document_id`, `chunk_id`, `version`, and `retrieval_score`.
- **FR-012**: System MUST refuse or transfer when evidence is insufficient, contradictory, stale, unapproved, or outside tenant/ACL scope.
- **FR-013**: System MUST maintain conversation context across turns without treating retrieved or caller-provided text as system instructions.
- **FR-014**: System MUST ask clarification questions when required slots are missing and the scenario allows self-service.
- **FR-015**: System MUST detect intents at least for FAQ, business hours, pricing/plan, reservation/order status, document request, department routing, complaint, refund/cancellation, and human handoff.
- **FR-016**: System MUST classify high-risk intents (legal, medical, financial, refund promise, contractual commitment, severe complaint, security incident) and transfer or block unsupported assertions.
- **FR-017**: System MUST support configured response templates for legally or operationally constrained language.
- **FR-018**: System MUST cap repeated fallback/clarification loops and transfer after a configured threshold.

#### シナリオ管理

- **FR-019**: Admins MUST be able to create, edit, test, submit for review, approve, publish, schedule, archive, and roll back call scenarios.
- **FR-020**: A scenario MUST define entry conditions, required slots, branch conditions, allowed actions, fallback messages, and handoff conditions.
- **FR-021**: Scenario changes MUST be versioned, and each call MUST record the scenario version used.
- **FR-022**: Scenario publication MUST require explicit reviewer/admin approval before activation; publish cannot silently approve a draft unless the caller has both approval and publish permissions.
- **FR-023**: Admins MUST be able to simulate a test conversation before publication and inspect expected AI responses, required slots, handoff triggers, and citations.
- **FR-024**: System SHOULD support A/B testing of scenarios after the MVP, but MVP MUST NOT require A/B testing to ship.

#### 人間転送

- **FR-025**: System MUST hand off immediately when the customer asks for a human.
- **FR-026**: System MUST trigger handoff for configured conditions including insufficient evidence, low ASR confidence, repeated misunderstanding, negative sentiment, high-risk intent, identity required but unavailable, operational outage, VIP customer, and AI capability boundary.
- **FR-027**: System MUST choose a handoff destination by queue, department, skill, business hours, and priority.
- **FR-028**: System MUST create a handoff package containing phone number, customer ID if known, intent, conversation summary, transcript, confirmed slots, cited knowledge, sentiment, handoff reason, and recommended next action.
- **FR-029**: System MUST record handoff outcome: created, queued, accepted, failed, unavailable, abandoned, or callback_requested.
- **FR-030**: If live transfer fails, System MUST provide a configured fallback (callback request, ticket creation, voicemail, or normal IVR).

#### 応対履歴・品質・分析

- **FR-031**: System MUST persist call metadata, transcript, AI responses, citations, tool calls, scenario path, handoff events, resolution status, disposition, and quality review state.
- **FR-032**: System MUST optionally persist audio recordings with retention policy and tenant-scoped access controls.
- **FR-033**: System MUST allow authorized users to search call history by call ID, date/time, customer ID, phone number, intent, result, handoff reason, and scenario.
- **FR-034**: System MUST mask PII, credentials, and payment data in logs, traces, model prompts where possible, and exported datasets.
- **FR-035**: System MUST audit access to call recordings, transcripts, customer identifiers, and quality reviews.
- **FR-036**: Supervisors MUST be able to evaluate call quality, mark hallucination or compliance issues, and create knowledge-improvement items.
- **FR-037**: System MUST expose operational metrics for call volume, answer rate, abandonment, service level, AHT, ACW, FCR, AI containment, handoff rate, handoff reasons, unresolved rate, CSAT, latency, and error rates.
- **FR-038**: System MUST define tenant-scoped, redacted export behavior for call and QA data; when export policy is enabled, exports are queued, and when disabled, requests return an audited `export_not_enabled` response.
- **FR-046**: Product MVP MUST provide either a redacted export endpoint or an explicit `export_not_enabled` response with audit logging; production enablement requires tenant policy configuration.

#### セキュリティ・コンプライアンス

- **FR-039**: System MUST enforce tenant and ACL boundaries before retrieval, answer generation, call history display, exports, and handoff package access.
- **FR-040**: System MUST not use caller data, audio, transcripts, or call summaries for model training unless an explicit tenant data-use policy permits it.
- **FR-041**: System MUST support retention and deletion policies for audio, transcript, AI logs, citations, and exported records.
- **FR-047**: Product MVP MUST include an admin-visible retention policy surface and a call deletion/redaction request path for call metadata, transcripts, summaries, handoff packages, recordings, and derived exports.
- **FR-042**: System MUST provide a configurable recording disclosure prompt and store whether it was played.
- **FR-043**: System MUST avoid storing raw card data or authentication secrets; if detected, values MUST be masked and the event flagged.
- **FR-044**: System MUST trace every call across telephony, ASR, orchestration, retrieval, LLM, TTS, handoff, and persistence using a correlation ID.
- **FR-045**: System MUST fail closed: if safety, ACL, groundedness, or provider policy checks cannot run, AI must not provide a definitive answer.

### Key Entities *(include if feature involves data)*

- **CallSession**: A single inbound or simulated phone call. Tracks call identity, tenant, caller metadata, timing, channel, state, scenario, handoff, recording, summary, and result.
- **ConversationTurn**: One customer or AI turn in a call. Stores transcript text, ASR confidence, AI response, citations, tool calls, latency, barge-in and DTMF data.
- **HandoffPackage**: The data passed to a human operator. Includes summary, transcript, known customer context, confirmed slots, citations, sentiment, reason, destination, and status.
- **CallScenario**: Versioned call-flow definition for an intent or journey. Defines required slots, branch conditions, allowed actions, response templates, handoff rules, and publication state.
- **ScenarioVersion**: Immutable published or draft version of a scenario with approver, timestamps, and rollback target.
- **KnowledgePolicy**: Reused and extended from the existing RAG platform. Defines what sources are eligible, current, approved, and permitted for phone use.
- **QualityEvaluation**: Supervisor review of a call. Records correctness, tone, handoff appropriateness, compliance issue, hallucination flag, suggested fix, and review status.
- **CallMetricSnapshot**: Aggregated operational metrics by tenant, queue, scenario, intent, and time bucket.
- **ProviderConfig**: Tenant/runtime configuration for telephony, ASR, TTS, LLM, CRM, handoff, retention, and recording disclosure behavior.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a seeded MVP corpus, 95% of answerable FAQ/business-hours/pricing test calls receive a grounded answer with at least one traceable citation.
- **SC-002**: 100% of calls where the customer asks for a human enter handoff flow within one AI turn.
- **SC-003**: 100% of insufficient-evidence test calls avoid definitive answers and create either a clarification or handoff outcome.
- **SC-004**: 100% of AI responses in persisted call history include answer text, evidence references, scenario version, and correlation ID.
- **SC-005**: PII/payment redaction tests show zero raw card numbers, authentication secrets, or internal auth headers in logs, traces, exported records, and handoff packages.
- **SC-006**: Product MVP dashboard shows call count, AI containment, handoff rate, top handoff reasons, unresolved rate, and p95 latency from persisted call data.
- **SC-007**: Scenario publication and rollback preserve version history, and a past call can be traced to the exact scenario version used.
- **SC-008**: When ASR/TTS/LLM/RAG/handoff providers fail in injected tests, the call follows configured fallback and no unsupported answer is spoken.

## Assumptions

- The first product MVP targets inbound calls only. Outbound campaigns are Phase 4+.
- The first implementation slice uses provider interfaces and a local telephony simulator for tests; production telephony adapters can be added behind configuration.
- Existing raku-rag RAG ingestion, ACL, citations, groundedness, provider policy, no-train, audit, and dashboard patterns are reused rather than reimplemented.
- The first MVP focuses on low-to-medium risk inquiries: business hours, FAQ, pricing/plan, reservation/order status, document request, and department routing.
- Refund decisions, legal responsibility, medical/financial advice, complex identity verification, card payment handling, and exception-heavy workflows are out of MVP scope. If such identity or business-process authority is required, the AI must transfer rather than self-serve.
- A human operator system may initially be represented by a queue/handoff API and operator console stub; deep PBX/ACD/CRM integrations can be phased.
- The product MVP is transcript-first. Audio recording persistence remains optional and disabled by default unless a tenant recording policy enables it.
- Recording disclosure behavior is configurable by tenant; the product should provide an announcement hook even when local law does not require explicit notice.
- All call data is tenant-scoped. Public API routes derive tenant/user identity from signed auth context, not request body overrides.
