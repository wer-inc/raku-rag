import { Inject, Injectable, Optional } from "@nestjs/common";

export const BEDROCK_CLAUDE_PROVIDER = "bedrock";
export const BEDROCK_CLAUDE_ANTHROPIC_VERSION = "bedrock-2023-05-31";
export const DEFAULT_BEDROCK_CLAUDE_SONNET_MODEL_ID = "anthropic.claude-sonnet-4-6";
export const DEFAULT_BEDROCK_CLAUDE_HAIKU_MODEL_ID = "anthropic.claude-haiku-4-5-20251001-v1:0";
export const BEDROCK_CLAUDE_RUNTIME_INVOKER = "BEDROCK_CLAUDE_RUNTIME_INVOKER";
export const BEDROCK_CLAUDE_COST_RECORDER = "BEDROCK_CLAUDE_COST_RECORDER";

export type ClaudeTask =
  | "final_answer"
  | "classification"
  | "enrichment"
  | "summarization"
  | "high_risk_assistance";

export interface ClaudeMessage {
  role: "user" | "assistant";
  content: string;
}

export interface BedrockClaudeInvokeModelRequest {
  modelId: string;
  contentType: "application/json";
  accept: "application/json";
  body: string;
}

export interface BedrockClaudeInvokeModelResponse {
  body: unknown;
}

export interface BedrockClaudeRuntimeInvoker {
  invokeModel(
    request: BedrockClaudeInvokeModelRequest,
  ): Promise<BedrockClaudeInvokeModelResponse> | BedrockClaudeInvokeModelResponse;
}

export interface BedrockClaudeGenerateRequest {
  tenant_id: string;
  task: ClaudeTask;
  messages: ClaudeMessage[];
  system?: string;
  max_tokens?: number;
  temperature?: number;
  query_id?: string;
  answer_id?: string;
  prompt_template_version?: string;
}

export interface ClaudeUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface ClaudeCostRecord {
  kind: "llm";
  tenant_id: string;
  provider: typeof BEDROCK_CLAUDE_PROVIDER;
  model: string;
  task: ClaudeTask;
  input_tokens: number;
  output_tokens: number;
  query_id?: string;
  answer_id?: string;
  prompt_template_version?: string;
}

export interface ClaudeCostRecorder {
  record(record: ClaudeCostRecord): Promise<string | void> | string | void;
}

export interface ClaudeTrace {
  provider: typeof BEDROCK_CLAUDE_PROVIDER;
  model: string;
  task: ClaudeTask;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  stop_reason?: string;
  cost_record_id?: string;
  prompt_template_version?: string;
}

export interface BedrockClaudeGenerateResult {
  text: string;
  model: string;
  task: ClaudeTask;
  usage: ClaudeUsage;
  trace: ClaudeTrace;
}

@Injectable()
export class BedrockClaudeService {
  constructor(
    @Optional()
    @Inject(BEDROCK_CLAUDE_RUNTIME_INVOKER)
    private readonly client?: BedrockClaudeRuntimeInvoker,
    @Optional()
    @Inject(BEDROCK_CLAUDE_COST_RECORDER)
    private readonly costRecorder?: ClaudeCostRecorder,
  ) {}

  generateFinalAnswer(
    request: Omit<BedrockClaudeGenerateRequest, "task">,
  ): Promise<BedrockClaudeGenerateResult> {
    return this.generate({ ...request, task: "final_answer" });
  }

  classify(request: Omit<BedrockClaudeGenerateRequest, "task">): Promise<BedrockClaudeGenerateResult> {
    return this.generate({ ...request, task: "classification" });
  }

  enrich(request: Omit<BedrockClaudeGenerateRequest, "task">): Promise<BedrockClaudeGenerateResult> {
    return this.generate({ ...request, task: "enrichment" });
  }

  summarize(request: Omit<BedrockClaudeGenerateRequest, "task">): Promise<BedrockClaudeGenerateResult> {
    return this.generate({ ...request, task: "summarization" });
  }

  assistHighRisk(
    request: Omit<BedrockClaudeGenerateRequest, "task">,
  ): Promise<BedrockClaudeGenerateResult> {
    return this.generate({ ...request, task: "high_risk_assistance" });
  }

  async generate(request: BedrockClaudeGenerateRequest): Promise<BedrockClaudeGenerateResult> {
    if (!this.client) {
      throw new Error("bedrock_claude_client_not_configured");
    }
    if (request.messages.length === 0) {
      throw new Error("Claude request requires at least one message");
    }

    const started = Date.now();
    const model = this.modelForTask(request.task);
    const response = await this.client.invokeModel({
      modelId: model,
      contentType: "application/json",
      accept: "application/json",
      body: JSON.stringify({
        anthropic_version: BEDROCK_CLAUDE_ANTHROPIC_VERSION,
        system: request.system,
        messages: request.messages.map((message) => ({
          role: message.role,
          content: [{ type: "text", text: message.content }],
        })),
        max_tokens: request.max_tokens ?? this.defaultMaxTokens(request.task),
        temperature: request.temperature ?? this.defaultTemperature(request.task),
      }),
    });
    const parsed = await this.parseClaudeResponse(response.body);
    const costRecordId = await this.recordCost(request, model, parsed.usage);
    return {
      text: parsed.text,
      model,
      task: request.task,
      usage: parsed.usage,
      trace: {
        provider: BEDROCK_CLAUDE_PROVIDER,
        model,
        task: request.task,
        latency_ms: Math.max(0, Date.now() - started),
        input_tokens: parsed.usage.input_tokens,
        output_tokens: parsed.usage.output_tokens,
        stop_reason: parsed.stopReason,
        cost_record_id: costRecordId,
        prompt_template_version: request.prompt_template_version,
      },
    };
  }

  modelForTask(task: ClaudeTask): string {
    if (task === "final_answer") {
      return process.env.BEDROCK_CLAUDE_SONNET_MODEL_ID ?? DEFAULT_BEDROCK_CLAUDE_SONNET_MODEL_ID;
    }
    return process.env.BEDROCK_CLAUDE_HAIKU_MODEL_ID ?? DEFAULT_BEDROCK_CLAUDE_HAIKU_MODEL_ID;
  }

  private defaultMaxTokens(task: ClaudeTask): number {
    return task === "final_answer" ? 2048 : 768;
  }

  private defaultTemperature(task: ClaudeTask): number {
    return task === "final_answer" ? 0.2 : 0;
  }

  private async parseClaudeResponse(
    body: unknown,
  ): Promise<{ text: string; usage: ClaudeUsage; stopReason?: string }> {
    const parsed = JSON.parse(await this.bodyToString(body)) as unknown;
    if (!this.isRecord(parsed) || !Array.isArray(parsed.content)) {
      throw new Error("invalid Bedrock Claude response: missing content");
    }
    const text = parsed.content
      .map((block) => (this.isRecord(block) && block.type === "text" && typeof block.text === "string" ? block.text : ""))
      .join("");
    const usageValue = this.isRecord(parsed.usage) ? parsed.usage : {};
    const inputTokens = typeof usageValue.input_tokens === "number" ? usageValue.input_tokens : 0;
    const outputTokens = typeof usageValue.output_tokens === "number" ? usageValue.output_tokens : 0;
    return {
      text,
      usage: { input_tokens: inputTokens, output_tokens: outputTokens },
      stopReason: typeof parsed.stop_reason === "string" ? parsed.stop_reason : undefined,
    };
  }

  private async bodyToString(body: unknown): Promise<string> {
    if (typeof body === "string") {
      return body;
    }
    if (Buffer.isBuffer(body)) {
      return body.toString("utf8");
    }
    if (body instanceof Uint8Array) {
      return Buffer.from(body).toString("utf8");
    }
    if (this.hasTransformToString(body)) {
      return await body.transformToString();
    }
    if (this.hasRead(body)) {
      return this.bodyToString(body.read());
    }
    throw new Error("invalid Bedrock Claude response: unreadable body");
  }

  private async recordCost(
    request: BedrockClaudeGenerateRequest,
    model: string,
    usage: ClaudeUsage,
  ): Promise<string | undefined> {
    if (!this.costRecorder) {
      return undefined;
    }
    const result = await this.costRecorder.record({
      kind: "llm",
      tenant_id: request.tenant_id,
      provider: BEDROCK_CLAUDE_PROVIDER,
      model,
      task: request.task,
      input_tokens: usage.input_tokens,
      output_tokens: usage.output_tokens,
      query_id: request.query_id,
      answer_id: request.answer_id,
      prompt_template_version: request.prompt_template_version,
    });
    return typeof result === "string" ? result : undefined;
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === "object";
  }

  private hasTransformToString(value: unknown): value is { transformToString(): string | Promise<string> } {
    return this.isRecord(value) && typeof value.transformToString === "function";
  }

  private hasRead(value: unknown): value is { read(): unknown } {
    return this.isRecord(value) && typeof value.read === "function";
  }
}
