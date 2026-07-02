// 022-ai-phone-rag — shared TS contracts for /v1/phone/* (contracts/phone-rag-openapi.md).

export type PhoneCallState =
  | "ringing"
  | "active"
  | "on_hold"
  | "handoff_pending"
  | "transferred"
  | "completed"
  | "abandoned"
  | "failed";

export type PhoneAiAction =
  | "ask_clarification"
  | "answer_with_citations"
  | "handoff"
  | "fallback"
  | "end_call";

export type PhoneHandoffStatus =
  | "created"
  | "queued"
  | "accepted"
  | "failed"
  | "unavailable"
  | "abandoned"
  | "callback_requested";

export type PhoneScenarioStatus =
  | "draft"
  | "in_review"
  | "approved"
  | "scheduled"
  | "published"
  | "archived";

export interface PhoneCitationRef {
  source_id: string;
  document_id: string;
  chunk_id: string;
  version?: string | null;
  retrieval_score: number;
  approval_status?: string | null;
  effective_date?: string | null;
  snippet_redacted?: string | null;
}

export interface PhoneUtterance {
  type?: "speech" | "dtmf" | "barge_in" | "hold" | "resume" | "hangup" | "provider_failure" | string;
  text?: string;
  dtmf_digits?: string;
  asr_confidence?: number;
  failed_provider?: string;
}

export interface PhoneSimulateCallRequest {
  caller?: { phone_number?: string; customer_id?: string };
  channel?: "simulator" | string;
  scenario_id?: string;
  collection_id?: string;
  utterances?: PhoneUtterance[];
  options?: { recording_enabled?: boolean; force_asr_confidence?: number };
}

export interface PhoneHandoffSummary {
  handoff_package_id: string;
  reason: string;
  destination_type: string;
  destination_id: string;
  status: PhoneHandoffStatus | string;
}

export interface PhoneSafetyDecision {
  answered_with_evidence: boolean;
  blocked_reason?: string | null;
}

export interface PhoneTurnResponse {
  api_version: "v1" | string;
  tenant_id: string;
  call_id: string;
  turn_id: string;
  call_state: PhoneCallState | string;
  ai_action: PhoneAiAction | string | null;
  ai_response_text: string | null;
  /** Voice-rendered short form for TTS (024 FR-L05). */
  speech_text?: string | null;
  tts_audio_ref: string | null;
  citations: PhoneCitationRef[];
  handoff: PhoneHandoffSummary | null;
  safety: PhoneSafetyDecision;
  correlation_id: string;
}

export interface PhoneSimulateCallResponse {
  api_version: "v1" | string;
  tenant_id: string;
  call_id: string;
  status: PhoneCallState | string;
  status_url: string;
  turns: PhoneTurnResponse[];
  correlation_id: string;
}

export interface PhoneTurnRequest {
  event_type?: PhoneUtterance["type"];
  text?: string;
  dtmf_digits?: string | null;
  asr_confidence?: number;
  collection_id?: string;
  failed_provider?: string;
}

export interface PhoneTranscriptTurn {
  turn_id: string;
  sequence_no: number;
  speaker: "caller" | "ai" | "system" | "operator" | string;
  event_type: string;
  redacted_text: string | null;
  created_at: string;
  asr_confidence?: number | null;
  dtmf_digits?: string;
  barge_in?: boolean;
  ai_action?: PhoneAiAction | string | null;
  speech_text?: string | null;
  tts_audio_ref?: string | null;
  citations?: PhoneCitationRef[];
  latency_ms?: Record<string, number | string>;
  safety?: PhoneSafetyDecision;
  handoff_reason?: string;
}

export interface PhoneCallSummaryItem {
  call_id: string;
  started_at: string;
  ended_at: string | null;
  caller_phone_number_masked: string | null;
  customer_id: string | null;
  intent: string | null;
  state: PhoneCallState | string;
  resolution_status: string | null;
  handoff_required: boolean;
  handoff_reason?: string | null;
  scenario_id: string | null;
  scenario_version_id: string | null;
}

export interface PhoneCallListResponse {
  api_version: "v1" | string;
  tenant_id: string;
  items: PhoneCallSummaryItem[];
  next_cursor: string | null;
  correlation_id: string;
}

export interface PhoneCallDetailResponse {
  api_version: "v1" | string;
  tenant_id: string;
  call_id: string;
  state: PhoneCallState | string;
  started_at: string;
  ended_at: string | null;
  caller_phone_number_masked: string | null;
  customer_id: string | null;
  intent: string | null;
  summary: string;
  resolution_status: string | null;
  scenario_id: string | null;
  scenario_version_id: string | null;
  recording_enabled: boolean;
  recording_disclosure_played: boolean;
  transcript_redaction_status: string;
  transcript: PhoneTranscriptTurn[];
  handoff: PhoneHandoffPackage | null;
  correlation_id: string;
}

export interface PhoneHandoffPackage {
  handoff_package_id: string;
  call_id: string;
  status: PhoneHandoffStatus | string;
  reason: string;
  priority: "low" | "normal" | "high" | "urgent" | string;
  destination_type: string;
  destination_id: string;
  customer: { customer_id: string | null; phone_number_masked: string | null };
  intent: string | null;
  summary: string;
  transcript_excerpt_redacted: string;
  confirmed_slots: Record<string, string>;
  citations: PhoneCitationRef[];
  sentiment: string | null;
  recommended_next_action: string | null;
  operator_id: string | null;
  accepted_at: string | null;
  failure_reason: string | null;
  created_at: string;
}

export interface PhoneHandoffResponse extends PhoneHandoffPackage {
  api_version: "v1" | string;
  tenant_id: string;
  correlation_id: string;
}

export interface PhoneHandoffAcceptRequest {
  operator_id?: string;
  queue_id?: string;
}

export interface PhoneHandoffAcceptResponse {
  api_version: "v1" | string;
  tenant_id: string;
  handoff_package_id: string;
  status: PhoneHandoffStatus | string;
  accepted_at: string | null;
  correlation_id: string;
}

export interface PhoneScenarioSummary {
  scenario_id: string;
  name: string;
  intent: string;
  status: PhoneScenarioStatus | string;
  active_version_id: string | null;
  updated_at: string;
}

export interface PhoneScenarioListResponse {
  api_version: "v1" | string;
  tenant_id: string;
  items: PhoneScenarioSummary[];
  correlation_id: string;
}

export interface PhoneScenarioCreateRequest {
  scenario_id?: string;
  name: string;
  intent: string;
  description?: string;
  owner_group?: string;
}

export interface PhoneScenarioVersionRequest {
  entry_conditions?: Array<Record<string, unknown>>;
  steps?: Array<Record<string, unknown>>;
  required_slots?: Array<{ slot: string; prompt?: string; max_attempts?: number }>;
  branch_conditions?: Array<Record<string, unknown>>;
  allowed_actions?: string[];
  handoff_conditions?: Array<{ reason: string; enabled?: boolean }>;
  fallback_message?: string;
  response_templates?: Array<Record<string, unknown>>;
}

export interface PhoneScenarioMutationResponse {
  api_version: "v1" | string;
  tenant_id: string;
  scenario_id: string;
  scenario_version_id?: string;
  status: PhoneScenarioStatus | string;
  active_version_id?: string | null;
  scheduled_publish_at?: string | null;
  rollback_target_version_id?: string | null;
  correlation_id: string;
}

export interface PhoneScenarioPreviewRequest {
  utterances: Array<string | PhoneUtterance>;
  collection_id?: string;
}

// --- 022 US4/US5: quality reviews, metrics, data lifecycle -------------------------------------

export interface PhoneQualityEvaluationRequest {
  answer_correctness?: number | null;
  tone_score?: number | null;
  handoff_appropriateness?: number | null;
  compliance_issue?: boolean;
  hallucination_detected?: boolean;
  privacy_issue?: boolean;
  suggested_fix?: string;
  knowledge_gap_topics?: string[];
}

export interface PhoneQualityEvaluation {
  evaluation_id: string;
  call_id: string;
  reviewer_id: string;
  reviewed_at: string;
  answer_correctness: number | null;
  tone_score: number | null;
  handoff_appropriateness: number | null;
  compliance_issue: boolean;
  hallucination_detected: boolean;
  privacy_issue: boolean;
  suggested_fix: string | null;
  knowledge_gap_topics: string[];
  review_status: string;
  improvement_item_id: string | null;
}

export interface PhoneQualityEvaluationResponse extends PhoneQualityEvaluation {
  api_version: "v1" | string;
  tenant_id: string;
  correlation_id: string;
}

export interface PhoneQualityEvaluationListResponse {
  api_version: "v1" | string;
  tenant_id: string;
  items: PhoneQualityEvaluation[];
  correlation_id: string;
}

export interface PhoneMetricsSummary {
  call_count: number;
  answered_count: number;
  answer_rate: number;
  ai_containment_rate: number;
  handoff_rate: number;
  unresolved_rate: number;
  terminal_count: number;
  average_handle_time_seconds: number;
  p95_total_turn_latency_ms: number | null;
  p95_rag_latency_ms: number | null;
}

export interface PhoneMetricPair {
  key: string;
  count: number;
}

export interface PhoneMetricsResponse {
  api_version: "v1" | string;
  tenant_id: string;
  summary: PhoneMetricsSummary;
  top_handoff_reasons: PhoneMetricPair[];
  top_intents: PhoneMetricPair[];
  knowledge_gap_topics: PhoneMetricPair[];
  correlation_id: string;
}

export interface PhoneRetentionPolicyResponse {
  api_version: "v1" | string;
  tenant_id: string;
  recording_enabled_default: boolean;
  transcript_retention_days: number;
  audio_retention_days: number | null;
  export_retention_days: number;
  export_enabled: boolean;
  correlation_id: string;
}

export interface PhoneExportResponse {
  api_version: "v1" | string;
  tenant_id: string;
  export_job_id: string;
  status: string;
  redacted: boolean;
  correlation_id: string;
}

export interface PhoneDeleteRequestResponse {
  api_version: "v1" | string;
  tenant_id: string;
  call_id: string;
  deletion_request_id: string;
  mode: string;
  status: string;
  correlation_id: string;
}

export interface PhoneScenarioPreviewResponse {
  api_version: "v1" | string;
  tenant_id: string;
  scenario_id: string;
  scenario_version_id: string;
  turns: Array<{
    ai_action: PhoneAiAction | string | null;
    ai_response_text: string | null;
    citations: PhoneCitationRef[];
  }>;
  would_handoff: boolean;
  correlation_id: string;
}
