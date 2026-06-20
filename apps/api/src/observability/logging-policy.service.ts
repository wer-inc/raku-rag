import { Injectable } from "@nestjs/common";
import type { LoggingPolicySettings, RawStorage } from "@raku-rag/shared";

const LOGGING_POLICY_DEFAULTS = {
  raw_user_query_storage: "disabled",
  raw_retrieved_context_storage: "disabled",
  model_input_storage: "disabled",
  model_output_storage: "disabled",
} as const;

export interface TraceContextItem {
  chunk_id: string;
  document_id: string;
  citation_id?: string;
  text?: string;
}

export interface TraceCitation {
  citation_id?: string;
  chunk_id: string;
  document_id: string;
}

export interface TraceModelMetadata {
  provider: string;
  model: string;
  model_version?: string;
}

export interface TraceCostMetadata {
  total?: number;
  currency?: string;
  records?: Array<{ kind: string; amount: number; cost_record_id?: string }>;
}

export interface AnswerTracePayload {
  trace_id: string;
  tenant_id: string;
  collection_id?: string;
  answer_id?: string;
  query?: string;
  retrieved_context?: TraceContextItem[];
  citations?: TraceCitation[];
  prompt_template_version?: string;
  model?: TraceModelMetadata;
  latency_ms?: number;
  cost?: TraceCostMetadata;
  model_input?: string;
  model_output?: string;
  metadata?: Record<string, unknown>;
}

export interface LangfuseTraceEvent {
  id: string;
  name: string;
  userId?: string;
  input?: string;
  output?: string;
  metadata: Record<string, unknown>;
  observations: Array<{
    id: string;
    type: "generation";
    name: string;
    input?: string;
    output?: string;
    metadata: Record<string, unknown>;
  }>;
}

export interface LoggingPolicyEnvelope {
  sampled: boolean;
  reason?: "sampled_out";
  event: LangfuseTraceEvent;
}

export const DEFAULT_LOGGING_POLICY: LoggingPolicySettings = {
  logging_policy_id: "default",
  tenant_id: "default",
  name: "Default logging policy",
  status: "active",
  raw_user_query_storage: "disabled",
  raw_retrieved_context_storage: "disabled",
  model_input_storage: "disabled",
  model_output_storage: "disabled",
  store_citation_ids: true,
  store_chunk_ids: true,
  store_prompt_template_version: true,
  store_model_metadata: true,
  store_latency: true,
  store_cost: true,
  production_sampling_rate: 1,
  profile_version: 1,
  schema_version: 1,
  effective_from: null,
  deprecated_at: null,
};

@Injectable()
export class LoggingPolicyEnforcer {
  sanitizeForLangfuse(
    policy: Partial<LoggingPolicySettings> | undefined,
    payload: AnswerTracePayload,
  ): LoggingPolicyEnvelope {
    const effective = this.withDefaults(policy, payload.tenant_id);
    const sampled = this.isSampled(effective.production_sampling_rate, payload.trace_id);
    const contextIds = this.contextIds(payload);
    const metadata: Record<string, unknown> = {
      tenant_id: payload.tenant_id,
      collection_id: payload.collection_id,
      answer_id: payload.answer_id,
      logging_policy_id: effective.logging_policy_id,
      raw_retrieved_context_storage: effective.raw_retrieved_context_storage,
      redaction_applied: true,
      ...payload.metadata,
    };

    if (effective.store_citation_ids) {
      metadata.citation_ids = contextIds.citation_ids;
    }
    if (effective.store_chunk_ids) {
      metadata.chunk_ids = contextIds.chunk_ids;
      metadata.document_ids = contextIds.document_ids;
    }
    if (effective.store_prompt_template_version) {
      metadata.prompt_template_version = payload.prompt_template_version;
    }
    if (effective.store_model_metadata) {
      metadata.model = payload.model;
    }
    if (effective.store_latency) {
      metadata.latency_ms = payload.latency_ms;
    }
    if (effective.store_cost) {
      metadata.cost = payload.cost;
    }

    const contextText = this.renderRetrievedContext(effective.raw_retrieved_context_storage, payload);
    if (contextText !== undefined) {
      metadata.retrieved_context = contextText;
    }

    const event: LangfuseTraceEvent = {
      id: payload.trace_id,
      name: "answer",
      userId: payload.tenant_id,
      input: this.redactByMode(effective.raw_user_query_storage, payload.query),
      output: this.redactByMode(effective.model_output_storage, payload.model_output),
      metadata: this.dropUndefined(metadata),
      observations: [
        {
          id: `${payload.trace_id}:generation`,
          type: "generation",
          name: "answer_generation",
          input: this.redactByMode(effective.model_input_storage, payload.model_input),
          output: this.redactByMode(effective.model_output_storage, payload.model_output),
          metadata: this.dropUndefined({
            model: effective.store_model_metadata ? payload.model : undefined,
            prompt_template_version: effective.store_prompt_template_version
              ? payload.prompt_template_version
              : undefined,
            latency_ms: effective.store_latency ? payload.latency_ms : undefined,
            cost: effective.store_cost ? payload.cost : undefined,
          }),
        },
      ],
    };
    return {
      sampled,
      reason: sampled ? undefined : "sampled_out",
      event: this.dropUndefinedDeep(event) as LangfuseTraceEvent,
    };
  }

  shouldStoreRaw(policy: Partial<LoggingPolicySettings> | undefined, kind: keyof typeof LOGGING_POLICY_DEFAULTS): boolean {
    const effective = this.withDefaults(policy, policy?.tenant_id ?? "default");
    return effective[kind] === "full_opt_in";
  }

  private withDefaults(
    policy: Partial<LoggingPolicySettings> | undefined,
    tenantId: string,
  ): LoggingPolicySettings {
    return {
      ...DEFAULT_LOGGING_POLICY,
      tenant_id: tenantId,
      ...policy,
      raw_user_query_storage: policy?.raw_user_query_storage ?? LOGGING_POLICY_DEFAULTS.raw_user_query_storage,
      raw_retrieved_context_storage:
        policy?.raw_retrieved_context_storage ?? LOGGING_POLICY_DEFAULTS.raw_retrieved_context_storage,
      model_input_storage: policy?.model_input_storage ?? LOGGING_POLICY_DEFAULTS.model_input_storage,
      model_output_storage: policy?.model_output_storage ?? LOGGING_POLICY_DEFAULTS.model_output_storage,
      production_sampling_rate: this.clampSampling(policy?.production_sampling_rate ?? 1),
    };
  }

  private renderRetrievedContext(policy: RawStorage, payload: AnswerTracePayload): string | undefined {
    if (policy === "disabled") {
      return undefined;
    }
    const joined = (payload.retrieved_context ?? [])
      .map((item) => `[${item.chunk_id}] ${item.text ?? ""}`)
      .join("\n");
    return this.redactByMode(policy, joined);
  }

  private redactByMode(mode: RawStorage, value: string | undefined): string | undefined {
    if (value === undefined || mode === "disabled") {
      return undefined;
    }
    if (mode === "full_opt_in") {
      return this.redactSecrets(value);
    }
    return this.redactAll(value);
  }

  private redactAll(value: string): string {
    return this.redactSecrets(value)
      .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[REDACTED:email]")
      .replace(/\b(?:\+?\d[\d -]{8,}\d)\b/g, "[REDACTED:phone]");
  }

  private redactSecrets(value: string): string {
    return value
      .replace(/\bsk-[A-Za-z0-9_-]{12,}\b/g, "[REDACTED:secret]")
      .replace(/\bAKIA[0-9A-Z]{16}\b/g, "[REDACTED:aws_access_key]")
      .replace(/\b(?:bearer|api[_-]?key)\s+[A-Za-z0-9._-]{12,}\b/gi, "[REDACTED:secret]");
  }

  private contextIds(payload: AnswerTracePayload): {
    citation_ids: string[];
    chunk_ids: string[];
    document_ids: string[];
  } {
    const citationIds = new Set<string>();
    const chunkIds = new Set<string>();
    const documentIds = new Set<string>();
    for (const item of payload.retrieved_context ?? []) {
      chunkIds.add(item.chunk_id);
      documentIds.add(item.document_id);
      if (item.citation_id) {
        citationIds.add(item.citation_id);
      }
    }
    for (const citation of payload.citations ?? []) {
      chunkIds.add(citation.chunk_id);
      documentIds.add(citation.document_id);
      if (citation.citation_id) {
        citationIds.add(citation.citation_id);
      }
    }
    return {
      citation_ids: [...citationIds],
      chunk_ids: [...chunkIds],
      document_ids: [...documentIds],
    };
  }

  private isSampled(rate: number, traceId: string): boolean {
    const clamped = this.clampSampling(rate);
    if (clamped <= 0) {
      return false;
    }
    if (clamped >= 1) {
      return true;
    }
    return this.hashToUnitInterval(traceId) < clamped;
  }

  private hashToUnitInterval(value: string): number {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967296;
  }

  private clampSampling(rate: number): number {
    if (!Number.isFinite(rate)) {
      return 0;
    }
    return Math.min(1, Math.max(0, rate));
  }

  private dropUndefined<T extends Record<string, unknown>>(value: T): T {
    return Object.fromEntries(Object.entries(value).filter(([, child]) => child !== undefined)) as T;
  }

  private dropUndefinedDeep(value: unknown): unknown {
    if (Array.isArray(value)) {
      return value.map((item) => this.dropUndefinedDeep(item));
    }
    if (value && typeof value === "object") {
      return Object.fromEntries(
        Object.entries(value)
          .filter(([, child]) => child !== undefined)
          .map(([key, child]) => [key, this.dropUndefinedDeep(child)]),
      );
    }
    return value;
  }
}
