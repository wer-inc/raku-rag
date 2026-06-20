import {
  BEDROCK_CLAUDE_ANTHROPIC_VERSION,
  DEFAULT_BEDROCK_CLAUDE_HAIKU_MODEL_ID,
  DEFAULT_BEDROCK_CLAUDE_SONNET_MODEL_ID,
  BedrockClaudeService,
  type BedrockClaudeInvokeModelRequest,
  type BedrockClaudeInvokeModelResponse,
  type BedrockClaudeRuntimeInvoker,
  type ClaudeCostRecord,
  type ClaudeCostRecorder,
} from "../src/llm/bedrock-claude.service";

class FakeClaudeRuntime implements BedrockClaudeRuntimeInvoker {
  readonly calls: BedrockClaudeInvokeModelRequest[] = [];

  constructor(private readonly responses: unknown[]) {}

  async invokeModel(request: BedrockClaudeInvokeModelRequest): Promise<BedrockClaudeInvokeModelResponse> {
    this.calls.push(request);
    const response = this.responses[Math.min(this.calls.length - 1, this.responses.length - 1)];
    return { body: Buffer.from(JSON.stringify(response), "utf8") };
  }
}

class FakeClaudeCostRecorder implements ClaudeCostRecorder {
  readonly records: ClaudeCostRecord[] = [];

  record(record: ClaudeCostRecord): string {
    this.records.push(record);
    return "cost_llm_1";
  }
}

const claudeResponse = {
  id: "msg_1",
  type: "message",
  role: "assistant",
  content: [{ type: "text", text: "Use the cited reset procedure." }],
  stop_reason: "end_turn",
  usage: { input_tokens: 12, output_tokens: 34 },
};

describe("Bedrock Claude service", () => {
  afterEach(() => {
    delete process.env.BEDROCK_CLAUDE_SONNET_MODEL_ID;
    delete process.env.BEDROCK_CLAUDE_HAIKU_MODEL_ID;
  });

  it("uses Sonnet for final answers and sends the Bedrock Claude Messages payload", async () => {
    const client = new FakeClaudeRuntime([claudeResponse]);
    const cost = new FakeClaudeCostRecorder();
    const service = new BedrockClaudeService(client, cost);

    const result = await service.generateFinalAnswer({
      tenant_id: "tenant_a",
      query_id: "query_1",
      answer_id: "answer_1",
      prompt_template_version: "answer:v3",
      system: "Answer only from cited context.",
      messages: [{ role: "user", content: "How do I reset alarm E-152?" }],
      max_tokens: 333,
      temperature: 0.1,
    });

    expect(client.calls).toHaveLength(1);
    expect(client.calls[0].modelId).toBe(DEFAULT_BEDROCK_CLAUDE_SONNET_MODEL_ID);
    expect(JSON.parse(client.calls[0].body)).toEqual({
      anthropic_version: BEDROCK_CLAUDE_ANTHROPIC_VERSION,
      system: "Answer only from cited context.",
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: "How do I reset alarm E-152?" }],
        },
      ],
      max_tokens: 333,
      temperature: 0.1,
    });
    expect(result.text).toBe("Use the cited reset procedure.");
    expect(result.task).toBe("final_answer");
    expect(result.trace.model).toBe(DEFAULT_BEDROCK_CLAUDE_SONNET_MODEL_ID);
    expect(result.trace.input_tokens).toBe(12);
    expect(result.trace.output_tokens).toBe(34);
    expect(result.trace.cost_record_id).toBe("cost_llm_1");
    expect(result.trace.prompt_template_version).toBe("answer:v3");
    expect(cost.records).toEqual([
      expect.objectContaining({
        kind: "llm",
        tenant_id: "tenant_a",
        provider: "bedrock",
        model: DEFAULT_BEDROCK_CLAUDE_SONNET_MODEL_ID,
        task: "final_answer",
        input_tokens: 12,
        output_tokens: 34,
        query_id: "query_1",
        answer_id: "answer_1",
      }),
    ]);
  });

  it("uses Haiku-class Claude for classification, enrichment, summarization, and high-risk assistance", async () => {
    const client = new FakeClaudeRuntime([claudeResponse]);
    const service = new BedrockClaudeService(client);
    const base = {
      tenant_id: "tenant_a",
      messages: [{ role: "user" as const, content: "Short helper task" }],
    };

    await service.classify(base);
    await service.enrich(base);
    await service.summarize(base);
    await service.assistHighRisk(base);

    expect(client.calls.map((call) => call.modelId)).toEqual([
      DEFAULT_BEDROCK_CLAUDE_HAIKU_MODEL_ID,
      DEFAULT_BEDROCK_CLAUDE_HAIKU_MODEL_ID,
      DEFAULT_BEDROCK_CLAUDE_HAIKU_MODEL_ID,
      DEFAULT_BEDROCK_CLAUDE_HAIKU_MODEL_ID,
    ]);
    for (const call of client.calls) {
      const body = JSON.parse(call.body) as { max_tokens: number; temperature: number };
      expect(body.max_tokens).toBe(768);
      expect(body.temperature).toBe(0);
    }
  });

  it("allows model IDs to be overridden and fails closed without a runtime client", async () => {
    process.env.BEDROCK_CLAUDE_SONNET_MODEL_ID = "custom-sonnet";
    process.env.BEDROCK_CLAUDE_HAIKU_MODEL_ID = "custom-haiku";
    const service = new BedrockClaudeService();

    expect(service.modelForTask("final_answer")).toBe("custom-sonnet");
    expect(service.modelForTask("classification")).toBe("custom-haiku");
    await expect(
      service.generate({
        tenant_id: "tenant_a",
        task: "final_answer",
        messages: [{ role: "user", content: "hello" }],
      }),
    ).rejects.toThrow(/bedrock_claude_client_not_configured/);
  });
});
