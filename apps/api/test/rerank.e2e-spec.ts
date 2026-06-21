import {
  BEDROCK_COHERE_RERANK_API_VERSION,
  BEDROCK_COHERE_RERANK_MODEL_ID,
  BedrockCohereRerankService,
  type BedrockInvokeModelRequest,
  type BedrockInvokeModelResponse,
  type BedrockRuntimeInvoker,
  type RerankCandidate,
  type RerankCostRecord,
  type RerankCostRecorder,
} from "../src/rerank/bedrock-cohere-rerank.service";

class FakeBedrockRuntime implements BedrockRuntimeInvoker {
  readonly calls: BedrockInvokeModelRequest[] = [];

  constructor(
    private readonly response: unknown,
    private readonly fail: boolean = false,
  ) {}

  async invokeModel(request: BedrockInvokeModelRequest): Promise<BedrockInvokeModelResponse> {
    this.calls.push(request);
    if (this.fail) {
      throw new Error("bedrock unavailable");
    }
    return { body: Buffer.from(JSON.stringify(this.response), "utf8") };
  }
}

class FakeCostRecorder implements RerankCostRecorder {
  readonly records: RerankCostRecord[] = [];

  record(record: RerankCostRecord): string {
    this.records.push(record);
    return "cost_rerank_1";
  }
}

function candidate(id: number, score: number = 1 / (id + 1)): RerankCandidate {
  return {
    chunk_id: `chunk_${id}`,
    document_id: `doc_${id}`,
    text: `candidate ${id} text`,
    retrieval_score: score,
  };
}

describe("Bedrock Cohere rerank service", () => {
  it("invokes Cohere Rerank 3.5 on Bedrock and records score, latency, and cost trace", async () => {
    const client = new FakeBedrockRuntime({
      results: [
        { index: 2, relevance_score: 0.91 },
        { index: 0, relevance_score: 0.72 },
        { index: 1, relevance_score: 0.11 },
      ],
    });
    const cost = new FakeCostRecorder();
    const service = new BedrockCohereRerankService(client, cost);

    const result = await service.rerank({
      tenant_id: "tenant_a",
      retrieval_profile_id: "retrieval_default",
      query_id: "query_1",
      answer_id: "answer_1",
      query: "alarm E-152 reset",
      candidates: [candidate(0), candidate(1), candidate(2)],
      rerank_candidate_limit: 20,
      final_context_limit: 5,
    });

    expect(client.calls).toHaveLength(1);
    expect(client.calls[0].modelId).toBe(BEDROCK_COHERE_RERANK_MODEL_ID);
    expect(client.calls[0].contentType).toBe("application/json");
    expect(client.calls[0].accept).toBe("*/*");
    expect(JSON.parse(client.calls[0].body)).toEqual({
      query: "alarm E-152 reset",
      documents: ["candidate 0 text", "candidate 1 text", "candidate 2 text"],
      api_version: BEDROCK_COHERE_RERANK_API_VERSION,
    });

    expect(result.candidates.map((item) => item.chunk_id)).toEqual(["chunk_2", "chunk_0", "chunk_1"]);
    expect(result.candidates[0].rerank_score).toBe(0.91);
    expect(result.trace.status).toBe("succeeded");
    expect(result.trace.candidate_count).toBe(3);
    expect(result.trace.final_context_count).toBe(3);
    expect(result.trace.selected_chunk_ids).toEqual(["chunk_2", "chunk_0", "chunk_1"]);
    expect(result.trace.scores).toEqual({ chunk_0: 0.72, chunk_1: 0.11, chunk_2: 0.91 });
    expect(result.trace.latency_ms).toBeGreaterThanOrEqual(0);
    expect(result.trace.cost_record_id).toBe("cost_rerank_1");
    expect(cost.records).toEqual([
      expect.objectContaining({
        kind: "rerank",
        tenant_id: "tenant_a",
        provider: "bedrock",
        model: BEDROCK_COHERE_RERANK_MODEL_ID,
        candidate_count: 3,
        billable_unit: "document",
        billable_unit_count: 3,
        retrieval_profile_id: "retrieval_default",
        query_id: "query_1",
        answer_id: "answer_1",
      }),
    ]);
  });

  it("bounds Bedrock input to configured candidates and returns only 5-12 final contexts", async () => {
    const client = new FakeBedrockRuntime({
      results: Array.from({ length: 20 }, (_, index) => ({
        index,
        relevance_score: 1 - index / 100,
      })),
    });
    const service = new BedrockCohereRerankService(client);

    const result = await service.rerank({
      tenant_id: "tenant_a",
      query: "bounded candidate set",
      candidates: Array.from({ length: 90 }, (_, index) => candidate(index)),
      rerank_candidate_limit: 20,
      final_context_limit: 5,
    });
    const body = JSON.parse(client.calls[0].body) as { documents: string[] };

    expect(body.documents).toHaveLength(20);
    expect(result.trace.candidate_count).toBe(20);
    expect(result.candidates).toHaveLength(5);
    await expect(
      service.rerank({
        tenant_id: "tenant_a",
        query: "too many",
        candidates: [candidate(0)],
        rerank_candidate_limit: 81,
        final_context_limit: 5,
      }),
    ).rejects.toThrow(/between 1 and 80/);
    await expect(
      service.rerank({
        tenant_id: "tenant_a",
        query: "too few final",
        candidates: [candidate(0)],
        rerank_candidate_limit: 20,
        final_context_limit: 4,
      }),
    ).rejects.toThrow(/between 5 and 12/);
  });

  it("skips rerank on Bedrock failure and preserves bounded candidate order for caller gates", async () => {
    const client = new FakeBedrockRuntime({ results: [] }, true);
    const cost = new FakeCostRecorder();
    const service = new BedrockCohereRerankService(client, cost);

    const result = await service.rerank({
      tenant_id: "tenant_a",
      query: "fallback",
      candidates: [candidate(0, 0.2), candidate(1, 0.9), candidate(2, 0.4)],
      rerank_candidate_limit: 20,
      final_context_limit: 5,
    });

    expect(result.trace.status).toBe("skipped");
    expect(result.trace.error_reason).toBe("bedrock unavailable");
    expect(result.candidates.map((item) => item.chunk_id)).toEqual(["chunk_0", "chunk_1", "chunk_2"]);
    expect(result.trace.scores).toEqual({});
    expect(cost.records).toHaveLength(0);
  });
});
