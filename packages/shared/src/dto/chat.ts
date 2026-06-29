import type { Citation } from "./answer.js";

export type ChatResponseState =
  | "sending"
  | "thinking"
  | "checking_rag"
  | "checking_action"
  | "delayed"
  | "retryable_error"
  | "handoff_available"
  | "completed";

export type ChatSessionStatus =
  | "active"
  | "waiting_user"
  | "handoff_pending"
  | "ticket_created"
  | "resolved"
  | "closed";

export type ChatAiAction =
  | "collect_slot"
  | "answer_with_citations"
  | "ask_clarification"
  | "confirm_action"
  | "ticket_created"
  | "handoff"
  | "fallback";

export interface ChatQuickReply {
  label: string;
  value: string;
}

export interface ChatAssistantMessage {
  message_id: string;
  message: string;
  message_type: "text" | "form" | "handoff" | string;
  ai_action: ChatAiAction | string;
  quick_replies: ChatQuickReply[];
  citations: Citation[];
}

export interface ChatConversationState {
  status: ChatSessionStatus | string;
  response_state?: ChatResponseState;
  current_intent?: string | null;
  current_step?: string | null;
  scenario_id?: string | null;
  scenario_version_id?: string | null;
  collected_slots?: Record<string, string>;
  missing_slots?: string[];
  summary?: string;
  handoff_required?: boolean;
}

export interface ChatRagInteraction {
  rag_interaction_id: string;
  status: string;
  answerable: boolean;
  confidence: number | null;
  no_answer_reason?: string | null;
  trace_id?: string | null;
  latency_ms: number;
  citations?: Citation[];
  source_policy_id?: string | null;
}

export interface ChatHandoffPackage {
  handoff_package_id: string;
  session_id: string;
  status: "queued" | "assigned" | "closed" | string;
  reason: string;
  priority?: "low" | "normal" | "high" | string;
  summary?: string;
  collected_slots?: Record<string, string>;
  missing_slots?: string[];
  rag_citations?: Citation[];
  recommended_action?: string;
}

export interface ChatTicketStub {
  ticket_id: string;
  status: "created" | "queued" | string;
  idempotency_key?: string;
  created_at?: string;
}

export interface ChatCreateSessionRequest {
  channel?: "web_chat" | "public_widget" | string;
  initial_message?: string;
  collection_id?: string;
  metadata?: Record<string, unknown>;
}

export interface ChatPublicWidgetSessionRequest {
  widget_token: string;
  initial_message?: string;
  metadata?: Record<string, unknown>;
}

export interface ChatCreateSessionResponse {
  api_version: "v1" | string;
  tenant_id: string;
  session_id: string;
  status: ChatSessionStatus | string;
  processed_initial_message: boolean;
  user_message_id?: string;
  assistant_message?: ChatAssistantMessage;
  state?: ChatConversationState;
  rag?: ChatRagInteraction | null;
  handoff?: ChatHandoffPackage | null;
  ticket?: ChatTicketStub | null;
  correlation_id: string;
}

export interface ChatMessageRequest {
  message: string;
  client_message_id?: string;
  collection_id?: string;
  stream?: boolean;
}

export interface ChatMessageResponse {
  api_version: "v1" | string;
  tenant_id: string;
  session_id: string;
  status?: ChatSessionStatus | string;
  user_message_id: string;
  assistant_message: ChatAssistantMessage;
  state: ChatConversationState;
  rag?: ChatRagInteraction | null;
  handoff?: ChatHandoffPackage | null;
  ticket?: ChatTicketStub | null;
  correlation_id: string;
}

export interface ChatStoredMessage {
  message_id: string;
  role: "user" | "assistant" | "system" | "operator" | string;
  content_redacted: string;
  created_at?: string;
  message?: string;
  message_type?: string;
  ai_action?: string | null;
  quick_replies?: ChatQuickReply[];
  citations?: Citation[];
}

export interface ChatSessionDetailResponse {
  api_version: "v1" | string;
  tenant_id: string;
  session_id: string;
  status: ChatSessionStatus | string;
  current_intent?: string | null;
  scenario_id?: string | null;
  scenario_version_id?: string | null;
  summary?: string;
  messages: ChatStoredMessage[];
  state: ChatConversationState;
  handoff?: ChatHandoffPackage | null;
  ticket?: ChatTicketStub | null;
  correlation_id: string;
}

export interface ChatSessionSummary {
  session_id: string;
  started_at: string;
  last_message_at: string;
  current_intent?: string | null;
  status: ChatSessionStatus | string;
  resolution_status?: string;
  handoff_required: boolean;
  scenario_version_id?: string | null;
}

export interface ChatSessionListResponse {
  api_version: "v1" | string;
  tenant_id: string;
  items: ChatSessionSummary[];
  next_cursor: string | null;
  correlation_id: string;
}

export interface ChatHandoffRequest {
  reason?: string;
  comment?: string;
}

export interface ChatHandoffResponse {
  api_version: "v1" | string;
  tenant_id: string;
  session_id: string;
  handoff_package_id: string;
  status: string;
  reason: string;
  correlation_id: string;
}

export interface ChatFeedbackRequest {
  message_id?: string;
  rating?: number;
  issue_type?: "wrong_answer" | "grounding_issue" | "tone_issue" | "handoff_issue" | "rag_gap" | string;
  comment?: string;
}

export interface ChatFeedbackResponse {
  api_version: "v1" | string;
  tenant_id: string;
  evaluation_id: string;
  improvement_item_id?: string | null;
  correlation_id: string;
}

export interface ChatMetricsResponse {
  api_version: "v1" | string;
  tenant_id: string;
  summary: {
    conversation_count: number;
    bot_resolution_rate: number;
    handoff_rate: number;
    unanswered_rate: number;
    rag_answerable_rate: number;
    average_turns: number;
    p95_response_latency_ms: number;
  };
  top_intents: Array<{ key: string; count: number }>;
  top_handoff_reasons: Array<{ key: string; count: number }>;
  correlation_id: string;
}

export type ChatbotSourceExposureMode =
  | "disabled"
  | "internal_authenticated"
  | "external_authenticated"
  | "external_anonymous";

export interface ChatbotSourceExposurePolicy {
  api_version?: "v1" | string;
  tenant_id?: string;
  policy_id: string;
  source_id: string;
  collection_id?: string;
  exposure_mode: ChatbotSourceExposureMode;
  allowed_channels?: string[];
  allowed_scenario_ids?: string[];
  allowed_intents?: string[];
  required_document_tags?: string[];
  blocked_document_tags?: string[];
  require_approved_effective?: boolean;
  allow_obsolete_primary_evidence?: boolean;
  allowed_domains?: string[];
  status?: "active" | "draft" | "archived" | string;
  unsupported_reason?: string;
  correlation_id?: string;
}

export interface ChatbotSourceExposureListResponse {
  api_version: "v1" | string;
  tenant_id: string;
  items: ChatbotSourceExposurePolicy[];
  correlation_id: string;
}

export interface ChatbotSourceExposureValidationResponse {
  api_version: "v1" | string;
  tenant_id: string;
  allowed: boolean;
  reasons: string[];
  correlation_id: string;
}

export interface ChatScenarioVersion {
  version_id: string;
  status: "draft" | "in_review" | "approved" | "published" | "scheduled" | "archived" | string;
  required_slots?: string[];
  optional_slots?: string[];
  steps?: Array<Record<string, unknown>>;
  validation_rules?: Array<Record<string, unknown>>;
  rag_policy?: Record<string, unknown>;
  actions?: Array<Record<string, unknown>>;
  response_templates?: Record<string, unknown>;
  handoff_conditions?: Array<Record<string, unknown>>;
  updated_at?: string;
  approved_by?: string | null;
  approved_at?: string | null;
  published_by?: string | null;
  published_at?: string | null;
}

export interface ChatScenarioResponse {
  api_version?: "v1" | string;
  tenant_id?: string;
  scenario_id: string;
  name: string;
  intents: string[];
  status: string;
  active_version_id?: string | null;
  versions: ChatScenarioVersion[];
  correlation_id?: string;
}

export interface ChatScenarioListResponse {
  api_version: "v1" | string;
  tenant_id: string;
  items: ChatScenarioResponse[];
  correlation_id: string;
}
