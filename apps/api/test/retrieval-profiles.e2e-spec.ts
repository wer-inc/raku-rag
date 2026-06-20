import type { RetrievalProfileSettings } from "@raku-rag/shared";
import { findIdentifierMatches, normalizeIdentifier } from "../src/retrieval/identifier-match";
import { RetrievalProfileService } from "../src/retrieval/retrieval-profile.service";

function profile(overrides: Partial<RetrievalProfileSettings> = {}): RetrievalProfileSettings {
  return {
    retrieval_profile_id: "default",
    tenant_id: "tenant_a",
    name: "Default retrieval profile",
    status: "active",
    metadata_filter_required: true,
    identifier_match_enabled: true,
    identifier_fields: ["equipment_id", "alarm_code", "property_id", "contract_id", "isin", "invoice_id"],
    vector_search_enabled: true,
    vector_top_k: 3,
    rerank_enabled: true,
    rerank_candidate_limit: 50,
    final_context_limit: 3,
    minimum_evidence_count: 1,
    fallback_behavior: "insufficient_evidence",
    profile_version: 1,
    schema_version: 1,
    effective_from: null,
    deprecated_at: null,
    ...overrides,
  };
}

describe("retrieval profile service", () => {
  const service = new RetrievalProfileService();

  it("normalizes identifiers across common business-code formats", () => {
    expect(normalizeIdentifier(" e-152 ")).toBe("E152");
    expect(normalizeIdentifier("JP-90K1-2345-6789")).toBe("JP90K123456789");
    expect(normalizeIdentifier("Room 12-A")).toBe("ROOM12A");

    const matches = findIdentifierMatches("Alarm E-152 on pump", { alarm_code: "E152" }, ["alarm_code"]);
    expect(matches).toHaveLength(1);
    expect(matches[0].field).toBe("alarm_code");
  });

  it("forbids vector-only retrieval profiles by default", () => {
    expect(() =>
      service.assertProfileSafe(
        profile({
          metadata_filter_required: false,
          identifier_match_enabled: false,
          vector_search_enabled: true,
          keyword_match_enabled: false,
        }),
      ),
    ).toThrow(/vector_only_disabled/);
  });

  it("unions metadata exact, identifier match, and pgvector candidates with bounded rerank", () => {
    const result = service.buildCandidateUnion(profile({ final_context_limit: 2, rerank_candidate_limit: 2 }), {
      query: "Alarm E-152 for equipment pump-12",
      metadata_filter: { document_type: "manual" },
      candidates: [
        {
          chunk_id: "c1",
          document_id: "d1",
          text: "manual with exact metadata",
          metadata: { document_type: "manual", equipment_id: "PUMP-12" },
          vector_score: 0.2,
        },
        {
          chunk_id: "c2",
          document_id: "d2",
          text: "alarm exact match",
          metadata: { document_type: "bulletin", alarm_code: "E152" },
          vector_score: 0.1,
        },
        {
          chunk_id: "c3",
          document_id: "d3",
          text: "semantic candidate",
          metadata: { document_type: "note" },
          vector_score: 0.9,
        },
      ],
    });

    expect(result).toHaveLength(2);
    expect(result.map((item) => item.chunk_id)).toContain("c1");
    expect(result.map((item) => item.chunk_id)).toContain("c2");
    expect(result.flatMap((item) => item.candidate_reasons)).toEqual(
      expect.arrayContaining(["metadata_exact", "identifier_exact"]),
    );
  });
});
