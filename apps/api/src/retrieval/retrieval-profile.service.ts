import { BadGatewayException, Injectable, NotFoundException } from "@nestjs/common";
import type { Request } from "express";
import type {
  AdminSettingsMutationResponse,
  RetrievalProfileBenchmarkRequest,
  RetrievalProfileBenchmarkResponse,
  RetrievalProfileSettings,
  RetrievalProfileUpsertRequest,
} from "@raku-rag/shared";
import { findIdentifierMatches } from "./identifier-match";
import { internalAuthHeaders } from "../auth/internal-auth";

export interface RetrievalCandidate {
  chunk_id: string;
  document_id: string;
  text: string;
  metadata: Record<string, unknown>;
  vector_score?: number;
  rerank_score?: number;
}

export interface CandidateUnionRequest {
  query: string;
  metadata_filter?: Record<string, unknown>;
  candidates: RetrievalCandidate[];
}

export interface RankedRetrievalCandidate extends RetrievalCandidate {
  candidate_reasons: string[];
  score: number;
}

@Injectable()
export class RetrievalProfileService {
  private baseUrl(): string {
    return process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
  }

  private principalHeaders(req: Request): Record<string, string> {
    const p = req.principal!;
    return {
      "x-raku-tenant-id": p.tenant_id,
      "x-raku-user-id": p.user_id,
      "x-raku-groups": JSON.stringify(p.groups),
      "x-raku-roles": JSON.stringify(p.roles),
      ...internalAuthHeaders(),
    };
  }

  private stripTenantOverrides(value: unknown): unknown {
    if (Array.isArray(value)) {
      return value.map((item) => this.stripTenantOverrides(item));
    }
    if (value && typeof value === "object") {
      const cleaned: Record<string, unknown> = {};
      for (const [key, child] of Object.entries(value)) {
        if (key !== "tenant_id") {
          cleaned[key] = this.stripTenantOverrides(child);
        }
      }
      return cleaned;
    }
    return value;
  }

  private async requestCore<T>(
    req: Request,
    method: "GET" | "POST" | "PUT",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const headers: Record<string, string> = {
      ...this.principalHeaders(req),
    };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
    }
    const upstream = await fetch(`${this.baseUrl()}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(this.stripTenantOverrides(body)),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (upstream.status === 404) {
      throw new NotFoundException("not found");
    }
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as T;
  }

  list(req: Request, collectionId?: string): Promise<RetrievalProfileSettings[]> {
    const params = new URLSearchParams();
    if (collectionId) {
      params.set("collection_id", collectionId);
    }
    const query = params.toString();
    return this.requestCore(req, "GET", `/internal/admin/retrieval-profiles${query ? `?${query}` : ""}`);
  }

  get(req: Request, retrievalProfileId: string): Promise<RetrievalProfileSettings> {
    return this.requestCore(req, "GET", `/internal/admin/retrieval-profiles/${encodeURIComponent(retrievalProfileId)}`);
  }

  upsert(
    req: Request,
    retrievalProfileId: string,
    body: RetrievalProfileUpsertRequest,
  ): Promise<AdminSettingsMutationResponse<RetrievalProfileSettings>> {
    return this.requestCore(
      req,
      "PUT",
      `/internal/admin/retrieval-profiles/${encodeURIComponent(retrievalProfileId)}`,
      body,
    );
  }

  benchmark(
    req: Request,
    retrievalProfileId: string,
    body: RetrievalProfileBenchmarkRequest,
  ): Promise<RetrievalProfileBenchmarkResponse> {
    return this.requestCore(
      req,
      "POST",
      `/internal/admin/retrieval-profiles/${encodeURIComponent(retrievalProfileId)}/benchmark`,
      body,
    );
  }

  assertProfileSafe(profile: Pick<
    RetrievalProfileSettings,
    "metadata_filter_required" | "identifier_match_enabled" | "vector_search_enabled" | "rerank_candidate_limit" | "final_context_limit" | "max_context_tokens"
  > & { keyword_match_enabled?: boolean }): void {
    const hasNonVectorGate =
      profile.metadata_filter_required ||
      profile.identifier_match_enabled ||
      Boolean(profile.keyword_match_enabled);
    if (profile.vector_search_enabled && !hasNonVectorGate) {
      throw new Error("vector_only_disabled: retrieval profile must use metadata or identifier gates");
    }
    if (profile.rerank_candidate_limit <= 0 || profile.rerank_candidate_limit > 80) {
      throw new Error("rerank_candidate_limit must be between 1 and 80");
    }
    if (profile.max_context_tokens <= 0) {
      throw new Error("max_context_tokens must be positive");
    }
    if ("final_context_limit" in profile && Number(profile.final_context_limit) <= 0) {
      throw new Error("final_context_limit must be positive");
    }
  }

  buildCandidateUnion(
    profile: RetrievalProfileSettings,
    request: CandidateUnionRequest,
  ): RankedRetrievalCandidate[] {
    this.assertProfileSafe(profile);
    const byChunk = new Map<string, RankedRetrievalCandidate>();
    const add = (candidate: RetrievalCandidate, reason: string, score: number) => {
      const existing = byChunk.get(candidate.chunk_id);
      if (existing) {
        existing.candidate_reasons = [...new Set([...existing.candidate_reasons, reason])];
        existing.score = Math.max(existing.score, score);
        return;
      }
      byChunk.set(candidate.chunk_id, {
        ...candidate,
        candidate_reasons: [reason],
        score,
      });
    };

    for (const candidate of request.candidates) {
      if (this.metadataMatches(candidate.metadata, request.metadata_filter ?? {})) {
        add(candidate, "metadata_exact", 1.0);
      }
      if (
        profile.identifier_match_enabled &&
        findIdentifierMatches(request.query, candidate.metadata, profile.identifier_fields).length > 0
      ) {
        add(candidate, "identifier_exact", 1.0);
      }
    }

    if (profile.vector_search_enabled) {
      [...request.candidates]
        .sort((a, b) => (b.vector_score ?? 0) - (a.vector_score ?? 0))
        .slice(0, Math.max(0, profile.vector_top_k))
        .forEach((candidate) => add(candidate, "pgvector", candidate.vector_score ?? 0));
    }

    const bounded = [...byChunk.values()]
      .sort((a, b) => (b.rerank_score ?? b.score) - (a.rerank_score ?? a.score))
      .slice(0, Math.min(profile.rerank_candidate_limit, 80));
    return bounded.slice(0, Math.max(1, profile.final_context_limit));
  }

  private metadataMatches(metadata: Record<string, unknown>, filter: Record<string, unknown>): boolean {
    const entries = Object.entries(filter).filter(([, value]) => value !== undefined && value !== "");
    if (entries.length === 0) {
      return false;
    }
    return entries.every(([key, value]) => String(metadata[key] ?? "") === String(value));
  }
}
