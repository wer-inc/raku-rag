import { Inject, Injectable, Optional } from "@nestjs/common";

export const BEDROCK_COHERE_RERANK_MODEL_ID = "cohere.rerank-v3-5:0";
export const BEDROCK_COHERE_RERANK_PROVIDER = "bedrock";
export const BEDROCK_COHERE_RERANK_API_VERSION = 2;
export const BEDROCK_RUNTIME_INVOKER = "BEDROCK_RUNTIME_INVOKER";
export const RERANK_COST_RECORDER = "RERANK_COST_RECORDER";
export const MIN_RERANK_CANDIDATE_LIMIT = 50;
export const MAX_RERANK_CANDIDATE_LIMIT = 80;
export const MIN_FINAL_CONTEXT_LIMIT = 5;
export const MAX_FINAL_CONTEXT_LIMIT = 12;

export interface BedrockInvokeModelRequest {
  modelId: string;
  contentType: "application/json";
  accept: "*/*";
  body: string;
}

export interface BedrockInvokeModelResponse {
  body: unknown;
}

export interface BedrockRuntimeInvoker {
  invokeModel(request: BedrockInvokeModelRequest): Promise<BedrockInvokeModelResponse> | BedrockInvokeModelResponse;
}

export interface RerankCandidate {
  chunk_id: string;
  document_id: string;
  text: string;
  retrieval_score?: number;
  metadata?: Record<string, unknown>;
}

export interface RerankedCandidate extends RerankCandidate {
  rerank_score?: number;
  original_rank: number;
  reranked_rank: number;
}

export interface BedrockCohereRerankRequest {
  tenant_id: string;
  query: string;
  candidates: RerankCandidate[];
  rerank_candidate_limit?: number;
  final_context_limit?: number;
  retrieval_profile_id?: string;
  query_id?: string;
  answer_id?: string;
}

export interface RerankCostRecord {
  kind: "rerank";
  tenant_id: string;
  provider: typeof BEDROCK_COHERE_RERANK_PROVIDER;
  model: typeof BEDROCK_COHERE_RERANK_MODEL_ID;
  candidate_count: number;
  billable_unit: "document";
  billable_unit_count: number;
  retrieval_profile_id?: string;
  query_id?: string;
  answer_id?: string;
}

export interface RerankCostRecorder {
  record(record: RerankCostRecord): Promise<string | void> | string | void;
}

export interface RerankTrace {
  status: "succeeded" | "skipped";
  provider: typeof BEDROCK_COHERE_RERANK_PROVIDER;
  model: typeof BEDROCK_COHERE_RERANK_MODEL_ID;
  candidate_count: number;
  final_context_count: number;
  candidate_chunk_ids: string[];
  selected_chunk_ids: string[];
  scores: Record<string, number>;
  latency_ms: number;
  cost_record_id?: string;
  error_reason?: string;
}

export interface BedrockCohereRerankResult {
  candidates: RerankedCandidate[];
  trace: RerankTrace;
}

interface CohereRerankResultItem {
  index: number;
  relevanceScore: number;
}

@Injectable()
export class BedrockCohereRerankService {
  constructor(
    @Optional()
    @Inject(BEDROCK_RUNTIME_INVOKER)
    private readonly client?: BedrockRuntimeInvoker,
    @Optional()
    @Inject(RERANK_COST_RECORDER)
    private readonly costRecorder?: RerankCostRecorder,
  ) {}

  async rerank(request: BedrockCohereRerankRequest): Promise<BedrockCohereRerankResult> {
    const candidateLimit = this.resolveCandidateLimit(request.rerank_candidate_limit);
    const finalContextLimit = this.resolveFinalContextLimit(request.final_context_limit);
    const bounded = request.candidates.slice(0, candidateLimit);
    const started = Date.now();

    if (bounded.length === 0) {
      return this.emptyResult(started);
    }
    if (!this.client) {
      return this.fallbackResult(bounded, finalContextLimit, started, "bedrock_client_not_configured");
    }

    try {
      const response = await this.client.invokeModel({
        modelId: BEDROCK_COHERE_RERANK_MODEL_ID,
        contentType: "application/json",
        accept: "*/*",
        body: JSON.stringify({
          query: request.query,
          documents: bounded.map((candidate) => candidate.text),
          api_version: BEDROCK_COHERE_RERANK_API_VERSION,
        }),
      });
      const scores = await this.parseScores(response.body);
      const ranked = this.applyScores(bounded, scores).slice(0, Math.min(finalContextLimit, bounded.length));
      const costRecordId = await this.recordCost(request, bounded.length);
      return {
        candidates: ranked,
        trace: this.trace("succeeded", bounded, ranked, scores, started, costRecordId),
      };
    } catch (error) {
      return this.fallbackResult(
        bounded,
        finalContextLimit,
        started,
        error instanceof Error && error.message ? error.message : "bedrock_rerank_failed",
      );
    }
  }

  private resolveCandidateLimit(limit: number | undefined): number {
    const value = limit ?? MIN_RERANK_CANDIDATE_LIMIT;
    if (!Number.isInteger(value) || value < MIN_RERANK_CANDIDATE_LIMIT || value > MAX_RERANK_CANDIDATE_LIMIT) {
      throw new Error("rerank_candidate_limit must be between 50 and 80");
    }
    return value;
  }

  private resolveFinalContextLimit(limit: number | undefined): number {
    const value = limit ?? 8;
    if (!Number.isInteger(value) || value < MIN_FINAL_CONTEXT_LIMIT || value > MAX_FINAL_CONTEXT_LIMIT) {
      throw new Error("final_context_limit must be between 5 and 12");
    }
    return value;
  }

  private async parseScores(body: unknown): Promise<CohereRerankResultItem[]> {
    const parsed = JSON.parse(await this.bodyToString(body)) as unknown;
    if (!this.isRecord(parsed) || !Array.isArray(parsed.results)) {
      throw new Error("invalid Bedrock Cohere rerank response: missing results");
    }
    return parsed.results.map((item) => this.parseScoreItem(item));
  }

  private parseScoreItem(item: unknown): CohereRerankResultItem {
    if (!this.isRecord(item)) {
      throw new Error("invalid Bedrock Cohere rerank response: result item must be object");
    }
    const index = typeof item.index === "number" && Number.isInteger(item.index) ? item.index : undefined;
    const relevance = item.relevance_score ?? item.relevanceScore ?? item.score;
    if (index === undefined || typeof relevance !== "number") {
      throw new Error("invalid Bedrock Cohere rerank response: result item missing index or score");
    }
    return { index, relevanceScore: relevance };
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
    throw new Error("invalid Bedrock Cohere rerank response: unreadable body");
  }

  private applyScores(candidates: RerankCandidate[], scores: CohereRerankResultItem[]): RerankedCandidate[] {
    const byIndex = new Map(scores.map((item) => [item.index, item.relevanceScore]));
    return candidates
      .map((candidate, index) => ({
        ...candidate,
        rerank_score: byIndex.get(index) ?? candidate.retrieval_score ?? 0,
        original_rank: index,
        reranked_rank: 0,
      }))
      .sort((a, b) => (b.rerank_score ?? 0) - (a.rerank_score ?? 0))
      .map((candidate, index) => ({
        ...candidate,
        reranked_rank: index,
      }));
  }

  private async recordCost(request: BedrockCohereRerankRequest, candidateCount: number): Promise<string | undefined> {
    if (!this.costRecorder) {
      return undefined;
    }
    const result = await this.costRecorder.record({
      kind: "rerank",
      tenant_id: request.tenant_id,
      provider: BEDROCK_COHERE_RERANK_PROVIDER,
      model: BEDROCK_COHERE_RERANK_MODEL_ID,
      candidate_count: candidateCount,
      billable_unit: "document",
      billable_unit_count: candidateCount,
      retrieval_profile_id: request.retrieval_profile_id,
      query_id: request.query_id,
      answer_id: request.answer_id,
    });
    return typeof result === "string" ? result : undefined;
  }

  private fallbackResult(
    candidates: RerankCandidate[],
    finalContextLimit: number,
    started: number,
    reason: string,
  ): BedrockCohereRerankResult {
    const selected = candidates.slice(0, Math.min(finalContextLimit, candidates.length)).map((candidate, index) => ({
      ...candidate,
      rerank_score: candidate.retrieval_score,
      original_rank: index,
      reranked_rank: index,
    }));
    return {
      candidates: selected,
      trace: this.trace("skipped", candidates, selected, [], started, undefined, reason),
    };
  }

  private emptyResult(started: number): BedrockCohereRerankResult {
    return {
      candidates: [],
      trace: this.trace("succeeded", [], [], [], started),
    };
  }

  private trace(
    status: "succeeded" | "skipped",
    candidates: RerankCandidate[],
    selected: RerankedCandidate[],
    scoreItems: CohereRerankResultItem[],
    started: number,
    costRecordId?: string,
    errorReason?: string,
  ): RerankTrace {
    const scores: Record<string, number> = {};
    for (const item of scoreItems) {
      const candidate = candidates[item.index];
      if (candidate) {
        scores[candidate.chunk_id] = item.relevanceScore;
      }
    }
    return {
      status,
      provider: BEDROCK_COHERE_RERANK_PROVIDER,
      model: BEDROCK_COHERE_RERANK_MODEL_ID,
      candidate_count: candidates.length,
      final_context_count: selected.length,
      candidate_chunk_ids: candidates.map((candidate) => candidate.chunk_id),
      selected_chunk_ids: selected.map((candidate) => candidate.chunk_id),
      scores,
      latency_ms: Math.max(0, Date.now() - started),
      cost_record_id: costRecordId,
      error_reason: errorReason,
    };
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
