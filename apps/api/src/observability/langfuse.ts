import { Inject, Injectable, Optional } from "@nestjs/common";
import type { LoggingPolicySettings } from "@raku-rag/shared";
import {
  type AnswerTracePayload,
  type LangfuseTraceEvent,
  LoggingPolicyEnforcer,
} from "./logging-policy.service";

export const LANGFUSE_TRACE_CLIENT = "LANGFUSE_TRACE_CLIENT";

export interface LangfuseTraceClient {
  sendTrace(event: LangfuseTraceEvent): Promise<void> | void;
}

export interface LangfuseExportResult {
  status: "exported" | "skipped" | "failed";
  reason?: "sampled_out" | "langfuse_client_not_configured" | "langfuse_export_failed";
  event: LangfuseTraceEvent;
  error?: string;
}

@Injectable()
export class LangfuseExporter {
  constructor(
    private readonly policyEnforcer: LoggingPolicyEnforcer,
    @Optional()
    @Inject(LANGFUSE_TRACE_CLIENT)
    private readonly client?: LangfuseTraceClient,
  ) {}

  async exportAnswerTrace(
    policy: Partial<LoggingPolicySettings> | undefined,
    payload: AnswerTracePayload,
  ): Promise<LangfuseExportResult> {
    const envelope = this.policyEnforcer.sanitizeForLangfuse(policy, payload);
    if (!envelope.sampled) {
      return {
        status: "skipped",
        reason: "sampled_out",
        event: envelope.event,
      };
    }
    if (!this.client) {
      return {
        status: "skipped",
        reason: "langfuse_client_not_configured",
        event: envelope.event,
      };
    }
    try {
      await this.client.sendTrace(envelope.event);
      return {
        status: "exported",
        event: envelope.event,
      };
    } catch (error) {
      return {
        status: "failed",
        reason: "langfuse_export_failed",
        event: envelope.event,
        error: error instanceof Error && error.message ? error.message : "Langfuse export failed",
      };
    }
  }
}
