import { LangfuseExporter, type LangfuseTraceClient } from "../src/observability/langfuse";
import {
  LoggingPolicyEnforcer,
  type AnswerTracePayload,
  type LangfuseTraceEvent,
} from "../src/observability/logging-policy.service";

class FakeLangfuseClient implements LangfuseTraceClient {
  readonly events: LangfuseTraceEvent[] = [];

  constructor(private readonly fail: boolean = false) {}

  sendTrace(event: LangfuseTraceEvent): void {
    this.events.push(event);
    if (this.fail) {
      throw new Error("langfuse down");
    }
  }
}

function payload(): AnswerTracePayload {
  return {
    trace_id: "trace_logging_1",
    tenant_id: "tenant_a",
    collection_id: "manuals",
    answer_id: "answer_1",
    query: "customer alice@example.com asked about raw query",
    retrieved_context: [
      {
        citation_id: "citation_1",
        chunk_id: "chunk_1",
        document_id: "doc_1",
        text: "RAW_CONTEXT_SECRET for alice@example.com with sk-abcdefghijklmnop",
      },
    ],
    citations: [{ citation_id: "citation_1", chunk_id: "chunk_1", document_id: "doc_1" }],
    prompt_template_version: "answer:v7",
    model: { provider: "bedrock", model: "anthropic.claude-sonnet-4-6", model_version: "2026-06" },
    latency_ms: 123,
    cost: { total: 0.42, currency: "USD", records: [{ kind: "llm", amount: 0.42 }] },
    model_input: "MODEL_INPUT_RAW alice@example.com sk-abcdefghijklmnop",
    model_output: "MODEL_OUTPUT_RAW bob@example.com sk-abcdefghijklmnop",
  };
}

describe("LoggingPolicyEnforcer and LangfuseExporter", () => {
  it("does not export raw retrieved context by default but keeps trace metadata", async () => {
    const enforcer = new LoggingPolicyEnforcer();
    const client = new FakeLangfuseClient();
    const exporter = new LangfuseExporter(enforcer, client);

    const result = await exporter.exportAnswerTrace(undefined, payload());
    const serialized = JSON.stringify(result.event);

    expect(result.status).toBe("exported");
    expect(client.events).toHaveLength(1);
    expect(enforcer.shouldStoreRaw(undefined, "raw_retrieved_context_storage")).toBe(false);
    expect(serialized).not.toContain("RAW_CONTEXT_SECRET");
    expect(serialized).not.toContain("MODEL_INPUT_RAW");
    expect(serialized).not.toContain("MODEL_OUTPUT_RAW");
    expect(serialized).not.toContain("alice@example.com");
    expect(serialized).not.toContain("sk-abcdefghijklmnop");
    expect(result.event.metadata.citation_ids).toEqual(["citation_1"]);
    expect(result.event.metadata.chunk_ids).toEqual(["chunk_1"]);
    expect(result.event.metadata.document_ids).toEqual(["doc_1"]);
    expect(result.event.metadata.prompt_template_version).toBe("answer:v7");
    expect(result.event.metadata.model).toEqual({
      provider: "bedrock",
      model: "anthropic.claude-sonnet-4-6",
      model_version: "2026-06",
    });
    expect(result.event.metadata.latency_ms).toBe(123);
    expect(result.event.metadata.cost).toEqual(payload().cost);
  });

  it("redacts opted-in query, context, model input, and model output before export", () => {
    const enforcer = new LoggingPolicyEnforcer();
    const result = enforcer.sanitizeForLangfuse(
      {
        tenant_id: "tenant_a",
        raw_user_query_storage: "redacted",
        raw_retrieved_context_storage: "redacted",
        model_input_storage: "redacted",
        model_output_storage: "redacted",
      },
      payload(),
    );
    const serialized = JSON.stringify(result.event);

    expect(result.event.input).toContain("[REDACTED:email]");
    expect(result.event.metadata.retrieved_context).toContain("[REDACTED:email]");
    expect(result.event.observations[0].input).toContain("[REDACTED:email]");
    expect(result.event.observations[0].output).toContain("[REDACTED:email]");
    expect(serialized).not.toContain("alice@example.com");
    expect(serialized).not.toContain("bob@example.com");
    expect(serialized).not.toContain("sk-abcdefghijklmnop");
  });

  it("samples out traces before calling Langfuse", async () => {
    const client = new FakeLangfuseClient();
    const exporter = new LangfuseExporter(new LoggingPolicyEnforcer(), client);

    const result = await exporter.exportAnswerTrace({ production_sampling_rate: 0 }, payload());

    expect(result.status).toBe("skipped");
    expect(result.reason).toBe("sampled_out");
    expect(client.events).toHaveLength(0);
  });

  it("does not let Langfuse export failures break the caller and still returns sanitized payload", async () => {
    const client = new FakeLangfuseClient(true);
    const exporter = new LangfuseExporter(new LoggingPolicyEnforcer(), client);

    const result = await exporter.exportAnswerTrace(
      {
        raw_retrieved_context_storage: "full_opt_in",
        model_output_storage: "full_opt_in",
      },
      payload(),
    );
    const serialized = JSON.stringify(result.event);

    expect(result.status).toBe("failed");
    expect(result.reason).toBe("langfuse_export_failed");
    expect(result.error).toBe("langfuse down");
    expect(client.events).toHaveLength(1);
    expect(serialized).toContain("RAW_CONTEXT_SECRET");
    expect(serialized).not.toContain("sk-abcdefghijklmnop");
  });
});
