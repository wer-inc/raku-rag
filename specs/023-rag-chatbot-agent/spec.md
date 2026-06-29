# Feature Specification: RAG-Connected Business ChatBot Agent

**Feature Branch**: `023-rag-chatbot-agent`

**Created**: 2026-06-28

**Status**: Draft

**Input**: User description from `/workspace/raku-rag/goal.md`: "既存RAGシステムを根拠エンジンとして呼び出しながら、お客さんと複数ターン会話し、必要な情報を聞き取り、回答・案内・手続き・人間への引き継ぎまで行う対話型ChatBot。"

## Scope Slices

- **P0 product MVP**: Web chat UI/API, immediate send acknowledgement, typing/progress states, timeout/retry/handoff UX, session/state management, intent classification, deterministic scenario/slot filling, backend scenario lifecycle APIs, existing RAG connector, grounded answers with citations, safe clarification, human handoff/ticket stub, conversation history, basic admin review, tenant isolation, and PII-safe logging. Scenario definitions may be created by API/seed fixtures; a polished scenario editor UI is not required in P0.
- **P1 operations slice**: Scenario management UI, slot definition UI, RAG filter configuration, response review, unanswered queue, feedback-to-RAG improvement flow, richer dashboard, streaming response, and optional Slack/email notification.
- **P2 expansion**: Live CRM/business API execution, agent-assist live chat, multi-language, A/B testing, prompt version management, automatic evaluation expansion, FAQ improvement suggestions, phone bot history integration, and external CCaaS/CRM adapters.

Story priorities (`Priority: P1/P2`) describe implementation/test sequencing inside Spec Kit. Product phase labels (`P0/P1/P2`) describe delivery slices. These labels must not be treated as the same axis when generating tasks.

## Product Definition

This feature is not a simple FAQ bot. It is a business conversation agent that:

- Maintains conversation state across turns.
- Chooses an intent and scenario.
- Collects required slots.
- Calls the existing RAG platform only when grounded knowledge is needed.
- Uses existing RAG citations, ACL, groundedness, deletion, feedback, and observability behavior.
- Hands off to humans or creates tickets when the bot cannot safely complete the journey.

The existing RAG platform remains the source of truth for ingestion, embeddings, vector search, ACL pre-filtering, grounded answer generation, citations, feedback storage, and knowledge lifecycle.

ChatBot access is deny-by-default and is narrower than generic RAG access. The effective knowledge scope for a chat turn is the intersection of:

- Verified tenant and user/session principal from signed auth or public widget/session token.
- Existing RAG tenant isolation, ACL pre-filter, tombstone/deletion, approval/effective-state, provider policy, and groundedness rules.
- Data source ChatBot exposure policy (`disabled`, `internal_authenticated`, `external_authenticated`, `external_anonymous`).
- Scenario `rag_policy` filters, allowed collection/source IDs, channel, and intent.
- External/public restrictions such as allowed domains, anonymous ACL scope, public document tags, and rate/abuse limits.

A data source can be indexed for internal RAG but still be unavailable to ChatBot, and a data source can be available to internal ChatBot while blocked from external/anonymous ChatBot.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 顧客が根拠付きで会話回答を受ける (Priority: P1)

顧客はWebチャットで自然文の問い合わせを送信し、Botは既存RAG基盤から得た根拠に基づいて回答する。回答には根拠リンク・文書バージョン・信頼度が紐づき、根拠不足や低信頼度の場合は断定せず、追加質問または人間引き継ぎに進む。

**Why this priority**: ChatBotの最小価値は、RAGを安全に会話UIへ接続し、根拠付きで回答できること。

**Independent Test**: Seeded tenantでチャットセッションを開始し、FAQ/料金/解約ポリシーの質問を送る。Bot応答、citation、RAG trace ID、会話履歴、根拠不足時の非断定応答を確認する。

**Acceptance Scenarios**:

1. **Given** 承認済みFAQに回答根拠がある, **When** 顧客が料金プランを質問する, **Then** Botは根拠付き回答、citation、quick replies、次アクションを返す。
2. **Given** RAGが `status=insufficient_evidence`、一時失敗、または低confidenceを返す, **When** 顧客が特別割引を質問する, **Then** Botは断定せず、確認不足を説明して人間引き継ぎ候補を作る。
3. **Given** 権限外文書だけが該当する, **When** 顧客がその内容を質問する, **Then** Botは制限文書の存在や内容を露出せず根拠不足として扱う。

---

### User Story 2 - 顧客が複数ターンの業務シナリオを進める (Priority: P1)

顧客が「解約したい」「導入相談したい」など手続き型の相談を行うと、Botはintentを判定し、シナリオに沿って必要情報を1つずつ聞き取り、入力形式を検証し、最後に確認を取ってチケット作成または受付完了に進む。

**Why this priority**: `goal.md` の核心は「一問一答」ではなく、会話を最後まで進める業務対話エージェントであること。

**Independent Test**: 解約または導入相談シナリオで、メール、会社名、契約ID、最終確認などのslotを複数ターンで収集し、conversation stateとticket stubが正しく更新されることを確認する。

**Acceptance Scenarios**:

1. **Given** 解約シナリオに `email` と `company_name` が必須slotとして定義されている, **When** 顧客が「解約したい」と言う, **Then** Botは不足slotだけを順に質問する。
2. **Given** 顧客がメール形式でない値を入力した, **When** Botがslotを検証する, **Then** Botは自然に修正入力を依頼し、失敗回数を記録する。
3. **Given** 手続き実行前に必要slotが揃っている, **When** 顧客が最終確認に同意する, **Then** Botは冪等なticket stubを作成し、受付番号を返す。

---

### User Story 3 - 顧客がいつでも人間へ引き継げる (Priority: P1)

顧客が人間を希望した場合、または高リスク、RAG根拠不足、連続失敗、業務API失敗、本人確認不足、システム障害が発生した場合、Botは会話を抱え込まず、人間またはチケットキューへ引き継ぐ。引き継ぎ時には会話要約、全文、収集済みslot、RAG根拠、転送理由、優先度を渡す。

**Why this priority**: 安全なChatBotには「答えない判断」と「人へ渡す判断」が不可欠。

**Independent Test**: `人に相談したい`、refund promise、legal claim、RAG timeout、連続slot失敗を投入し、handoff package/ticketが生成され、Botが無理に完結しないことを確認する。

**Acceptance Scenarios**:

1. **Given** 顧客が「担当者に聞きたい」と入力する, **When** Botがintentを判定する, **Then** Botは拒否せず `customer_requested_human` でhandoffを作成する。
2. **Given** 返金・補償・法的判断を含む問い合わせ, **When** Botがrisk flagsを検出する, **Then** Botは断定せず人間引き継ぎまたはticket作成へ進む。
3. **Given** handoffが作成された, **When** 管理者またはoperatorが詳細を見る, **Then** 要約、会話全文、収集済みslot、未確認項目、RAG citations、推奨対応が表示される。

---

### User Story 4 - 管理者が会話履歴・レビュー・改善を運用する (Priority: P2)

管理者またはreviewerは、会話一覧、会話詳細、RAG根拠、slot、handoff、ticket、ユーザー評価、誤回答を確認し、未回答や誤回答を既存RAGの改善/feedback flowへ送れる。

**Why this priority**: ChatBotは運用改善ループがないと劣化する。履歴とレビューはRAG改善の入力になる。

**Independent Test**: 完了済み/転送済み/低評価の会話を検索し、誤回答レビューを登録してRAG feedbackまたはimprovement itemに紐づくことを確認する。

**Acceptance Scenarios**:

1. **Given** 会話が完了している, **When** 管理者がsession detailを開く, **Then** message history、state、RAG trace、citations、handoff/ticket状態が表示される。
2. **Given** reviewerが誤回答を登録する, **When** issue typeを `rag_gap` にする, **Then** 既存RAG feedback/improvement flowへ根拠付きで送られる。

---

### User Story 5 - 運用責任者がChatBot KPIを確認する (Priority: P2)

運用責任者は、会話数、Bot解決率、転送率、未回答率、平均ターン数、平均応答時間、RAG成功率、低信頼率、CSAT、離脱率、シナリオ完了率、エラー率を確認できる。

**Why this priority**: Botの価値は回答品質だけでなく、解決率・転送率・未回答率・運用改善で測る必要がある。

**Independent Test**: 複数の解決済み、転送済み、未回答、低評価の会話をseedし、dashboard APIが正しい集計を返すことを確認する。

**Acceptance Scenarios**:

1. **Given** 複数の会話結果が保存されている, **When** dashboardを開く, **Then** Bot解決率、転送率、未回答率、RAG成功率が表示される。
2. **Given** RAG status から導出した未回答が増加している, **When** 未回答分析を見る, **Then** 該当intentとRAG改善候補が上位表示される。

---

### Edge Cases

- 顧客が「人間へ」と繰り返す場合、Botは説得せず即handoffする。
- 同一会話でintentが変わった場合、Botは現在のslotを保持しつつシナリオ変更を確認する。
- 顧客が入力したslotを訂正する場合、conversation stateは新しい値と訂正履歴を保持する。
- RAGがtimeout/temporarily_unavailable/budget_exceededを返す場合、Botは推測回答せずfallbackまたはhandoffに進む。
- HTTP応答が遅い場合、UIは無反応にせずtyping/progress状態を表示し、設定時間後にretryまたはhuman handoffを提示する。
- RAG根拠が古い、削除済み、権限外、承認待ちの場合、Botは正式回答に使わない。
- prompt injection、jailbreak、RAG文書内の命令文はシステム命令として扱わない。
- ユーザーがカード番号、認証情報、機密情報を入力した場合、ログ、trace、admin UI、handoff packageではmaskする。
- Botが業務API実行権限を持たない操作はticket/handoffに切り替える。
- チケット作成やhandoff通知の二重送信はidempotency keyで防ぐ。
- 匿名利用を許可する場合、RAGフィルタと履歴閲覧は匿名権限に制限する。
- データソースがChatBot利用不可または外部公開不可の場合、該当文書にユーザーACLがあってもChatBot回答には使わない。

## Requirements *(mandatory)*

### Functional Requirements

#### Chat UI / API

- **FR-001**: System MUST provide a Web Chat UI that supports sending messages, immediate optimistic display of the user's sent message, bot typing/progress states, rendering bot responses, citations, quick replies, forms, loading/error states, feedback, and an always-visible human handoff action.
- **FR-002**: System MUST expose versioned Chat API endpoints for session creation, message submission, session detail, handoff, feedback, admin history, backend scenario lifecycle, scenario preview, and metrics. A full scenario editor UI is P1.
- **FR-003**: System MUST support deterministic HTTP request/response, non-streaming responses for P0 without requiring WebSocket or SSE. The UI MUST create realtime feel through immediate acknowledgement, typing/progress labels, timeout handling, retry, and handoff affordances. SSE MAY be added in P1 without changing core message contracts; WebSocket remains reserved for live operator takeover or multi-party realtime flows.
- **FR-004**: System MUST derive tenant and user identity from signed auth context, not request body overrides.
- **FR-005**: System MUST support anonymous sessions only when explicitly configured and only with restricted ACL/filter scope.
- **FR-005a**: System MUST support external customer chat modes: authenticated external user and restricted anonymous public widget. These modes MUST use signed public session/widget context, not tenant IDs supplied in request bodies.

#### Conversation Orchestration

- **FR-006**: System MUST create a unique `session_id` and `correlation_id` for every chat session.
- **FR-007**: System MUST persist every user, assistant, system, and operator message with redacted display/export text.
- **FR-008**: System MUST maintain conversation state, including current intent, scenario, step, collected slots, missing slots, summary, last RAG trace, status, and handoff requirement.
- **FR-009**: System MUST classify intent on every user turn and detect intent changes.
- **FR-010**: System MUST prioritize multiple intents using configured scenario priority and safety rules.
- **FR-011**: System MUST support scenario selection by intent, entry condition, channel, tenant policy, and user attributes.
- **FR-012**: System MUST ask natural clarification questions when intent, required slots, or RAG evidence is insufficient.
- **FR-013**: System MUST cap repeated clarification/validation failures and hand off after a configured threshold.

#### Scenario / Slot Filling

- **FR-014**: System MUST support versioned chat scenarios with draft, in_review, approved, published, scheduled, and archived states.
- **FR-015**: Scenario publication MUST require explicit approval before activation.
- **FR-016**: Each scenario version MUST define steps, required/optional slots, validation rules, RAG usage, RAG filters, business action hooks, response templates, and handoff conditions.
- **FR-017**: System MUST record the exact scenario version used for each session and message.
- **FR-018**: System MUST extract multiple slots from one user message when possible and ask only for missing required slots.
- **FR-019**: System MUST support slot correction, skip, validation error handling, and audit of changed slot values.
- **FR-020**: System MUST require explicit final user confirmation before any state-changing business action or ticket creation.

#### Existing RAG Integration

- **FR-021**: System MUST reuse the existing 001 RAG platform for retrieval, answer generation, citations, ACL, groundedness, deletion, feedback, provider policy, and observability.
- **FR-022**: ChatBot MUST NOT create a separate vector store, embedding path, document ingestion path, or knowledge approval flow.
- **FR-023**: ChatBot MUST call the existing RAG answer/search contract through an adapter that forwards signed tenant/user claims and uses the existing request DTO shape unless `packages/shared` and OpenAPI are explicitly extended. Chat-specific session/message identifiers, conversation summary, intent, scenario, filters, language, and correlation ID MUST be stored in ChatBot `RagInteraction` metadata even when the current RAG DTO cannot accept all fields.
- **FR-024**: ChatBot MUST persist RAG request/response metadata including existing `status`, derived `answerable`, `confidence`, derived `no_answer_reason`, chat guardrail `risk_flags`, `correlation_id`/trace reference, `latency_ms`, and citations.
- **FR-025**: ChatBot MUST answer only when existing RAG status is `ok`, evidence is permitted/current/traceable, and ChatBot guardrails do not require handoff.
- **FR-026**: ChatBot MUST display or expose citations with existing RAG citation identifiers such as `source_id`, `document_id`, `chunk_id`, numeric `version`/document version, and `retrieval_score` for grounded answers.
- **FR-027**: ChatBot MUST not treat retrieved context, user text, or external tool output as system instructions.
- **FR-028**: ChatBot feedback and response reviews MUST link back to existing RAG feedback/improvement mechanisms.
- **FR-028a**: ChatBot MUST apply data source ChatBot exposure policy before using search/answer results. The effective source set is `principal ACL ∩ datasource chatbot exposure ∩ scenario rag_policy ∩ lifecycle/approval state`.
- **FR-028b**: Tenant admins MUST be able to configure, per data source or collection, whether it is unavailable to ChatBot, available to internal authenticated ChatBot, available to external authenticated ChatBot, or available to external anonymous ChatBot.
- **FR-028c**: External anonymous ChatBot MUST only use data sources and documents explicitly marked for anonymous/public chat and MUST exclude review-required, draft, obsolete-primary, deleted, private, secret, credential, or internal-only content.
- **FR-028d**: ChatBot MUST record which source exposure policy and scenario filter allowed each RAG interaction, without logging raw private content.

#### Guardrails / Handoff / Business Actions

- **FR-029**: System MUST trigger handoff when the user asks for a human.
- **FR-030**: System MUST trigger handoff or ticket creation for insufficient evidence, high-risk intent, low confidence, repeated misunderstanding, negative sentiment, identity requirement not satisfied, business API failure, permission boundary, VIP flag, or system outage.
- **FR-031**: System MUST create a handoff package containing session ID, user/customer identifiers if allowed, intent, summary, full redacted transcript, collected slots, missing slots, RAG citations, confidence, reason, priority, and recommended action.
- **FR-032**: System MUST support P0 ticket stub creation with idempotency keys; live CRM/ticket provider adapters are P2 unless explicitly enabled.
- **FR-033**: System MUST prevent duplicate business actions and duplicate tickets for the same confirmed request.
- **FR-034**: System MUST block unsupported refund promises, legal/medical/financial/insurance advice, disclosure of other-customer data, internal secrets, and ungrounded pricing/contract conditions.

#### Admin / Analytics / Lifecycle

- **FR-035**: Authorized users MUST be able to search chat sessions by session ID, date, user, email/company if permitted, intent, status, handoff reason, ticket status, rating, and scenario.
- **FR-036**: Authorized users MUST be able to inspect message history, state, slots, RAG traces, citations, handoffs, tickets, feedback, and evaluations.
- **FR-037**: Reviewers MUST be able to mark wrong answers, grounding issues, tone issues, handoff issues, and RAG gaps.
- **FR-038**: System MUST expose ChatBot metrics for conversation volume, bot resolution rate, handoff rate, unanswered rate, average turns, response latency, RAG answerable rate, low-confidence rate, CSAT, abandonment rate, scenario completion rate, and error rate.
- **FR-039**: System MUST support tenant-scoped retention, redacted export, and deletion/redaction request handling for chat sessions, messages, states, handoffs, tickets, evaluations, and derived analytics.

#### Security / Compliance / Observability

- **FR-040**: System MUST enforce tenant and ACL boundaries before RAG calls, response display, session history, admin history, export, feedback, and handoff access.
- **FR-041**: System MUST mask PII, credentials, card data, auth tokens, API keys, and internal headers in logs, traces, exports, admin default views, and handoff packages.
- **FR-042**: System MUST audit access to chat histories, PII fields, handoff packages, tickets, reviews, exports, and deletion requests.
- **FR-043**: System MUST not use chat data for model training unless an explicit tenant data-use policy permits it.
- **FR-044**: System MUST trace each session across chat API, orchestrator, scenario engine, RAG calls, business action stubs, handoff, persistence, and metrics using correlation IDs.
- **FR-045**: System MUST fail closed if ACL, groundedness, guardrail, provider policy, redaction, or RAG connector checks cannot run.
- **FR-046**: System MUST define client-visible response states for `sending`, `thinking`, `checking_rag`, `checking_action`, `delayed`, `retryable_error`, `handoff_available`, and `completed` so P0 HTTP responses never leave the user without visible progress.
- **FR-047**: System MUST reject or ignore public request attempts to override tenant, source IDs, collection IDs, ACL tags, exposure mode, or scenario filters. Public widget/session tokens and server-side tenant config are authoritative.

### Key Entities *(include if feature involves data)*

- **ChatSession**: A user conversation. Tracks tenant, user/channel, status, intent, scenario, timestamps, resolution, handoff, ticket, and summary.
- **ChatMessage**: A user/assistant/system/operator message. Stores content, redacted text, message type, quick replies, citations, token count, trace IDs, and feedback links.
- **ConversationState**: Current workflow state for a session, including current step, collected/missing slots, context summary, failure counters, and last RAG decision.
- **ChatScenario**: Logical scenario for an intent or business journey, with status and active version.
- **ScenarioVersion**: Immutable scenario definition with steps, slots, RAG filters, actions, templates, handoff rules, approval/publish metadata, and rollback target.
- **SlotDefinition / SlotValue**: Required/optional fields collected from users, including validation, correction history, sensitivity classification, and confirmation state.
- **RagInteraction**: Chat-side record of each RAG request/response, including filters, answerability, confidence, trace ID, sources, latency, and risk flags.
- **ChatCitationRef**: Traceable reference to existing RAG source/chunk/citation identifiers.
- **HandoffPackage**: Data passed to a human/operator/ticket queue with summary, transcript, slots, citations, reason, priority, and status.
- **TicketStub**: P0 deterministic business-action record for ticket creation or follow-up request.
- **ChatEvaluation / Feedback**: User or reviewer assessment linked to messages, citations, RAG interactions, and improvement items.
- **ChatMetricSnapshot**: Aggregated operational metrics by tenant, channel, scenario, intent, and time bucket.
- **ChatbotProviderConfig**: Tenant/runtime settings for RAG connector, business action provider, handoff provider, retention, no-train, logging, and anonymous access.
- **ChatbotSourceExposurePolicy**: Tenant-scoped policy that maps data sources/collections to ChatBot exposure modes, allowed channels, allowed scenarios/intents, required document tags, public widget restrictions, and audit metadata.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In seeded P0 scenarios, 95% of answerable FAQ/pricing/policy chat turns return grounded responses with at least one citation.
- **SC-002**: 100% of insufficient-evidence, low-confidence, or unavailable RAG test turns avoid definitive answers.
- **SC-003**: 100% of human-requested handoff turns create a handoff package or ticket within one bot turn.
- **SC-004**: 100% of completed scenario tests persist session state, collected slots, scenario version, RAG trace IDs, citations, and resolution status.
- **SC-005**: PII/secret redaction tests show zero raw card numbers, auth secrets, internal headers, or API keys in logs, exports, handoff packages, and default admin views.
- **SC-006**: Tenant isolation tests show users cannot view or infer other tenants' sessions, RAG evidence, handoffs, tickets, feedback, or metrics.
- **SC-007**: P0 dashboard shows conversation count, bot resolution rate, handoff rate, unanswered rate, RAG answerable rate, average turns, and p95 response latency.
- **SC-008**: RAG timeout/provider failure tests produce safe fallback or handoff and never generate ungrounded answer text.
- **SC-009**: P0 UI smoke shows the sent user message immediately, displays a bot typing/progress state before the HTTP response completes, and offers retry or handoff when the configured delay/timeout threshold is reached.
- **SC-010**: Access-scope tests show ChatBot never uses a data source that is not enabled for the current chat mode, even when the underlying user principal could access that source through generic RAG.

## Assumptions

- P0 uses the existing raku-rag auth/facade pattern and existing RAG answer/search APIs rather than an external RAG service.
- P0 uses deterministic scenario, ticket, notification, and business action stubs. Live CRM/ticket/Slack/email providers are adapters for later phases.
- P0 focuses on web chat. LINE/Slack/Teams/phone integration is post-MVP.
- P0 supports Japanese and uses existing RAG Japanese retrieval capabilities.
- Complex identity verification and state-changing business operations are not self-served in P0; they hand off or create ticket stubs after user confirmation.
- Scenario lifecycle APIs, versioning, approval, publish, and exact version traceability must exist from P0; the polished scenario management UI is P1.
- ChatBot does not weaken manufacturing or base RAG hard rules. Existing ACL, deletion, no-train, provider policy, and groundedness behavior remain authoritative.
