import { INestApplication } from "@nestjs/common";
import request from "supertest";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

// P0-T05 — NestJS skeleton boot + /v1 versioning.
describe("api skeleton (e2e)", () => {
  let app: INestApplication;

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    app = await createApp();
    await app.init();
  });
  afterAll(async () => app?.close());

  it("GET /v1/health -> 200 ok (public)", async () => {
    const res = await request(app.getHttpServer()).get("/v1/health");
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("ok");
    expect(res.headers["api-version"]).toBe("1");
  });

  it("non-/v1 route is 404 (versioning enforced)", async () => {
    const res = await request(app.getHttpServer()).get("/health");
    expect(res.status).toBe(404);
  });

  it("GET /v1/openapi.json exposes the fixed facade contract", async () => {
    const res = await request(app.getHttpServer()).get("/v1/openapi.json");
    expect(res.status).toBe(200);
    expect(res.body.openapi).toBe("3.0.3");
    expect(res.body.components.headers.ApiVersion.schema.enum).toContain("1");
    expect(res.body.paths["/health"].get.responses["200"].headers["api-version"].$ref).toBe(
      "#/components/headers/ApiVersion",
    );
    expect(res.body.paths["/health"].get.operationId).toBe("getHealth");
    expect(res.body.paths["/whoami"].get.security[0]).toHaveProperty("userToken");
    expect(res.body.paths["/answer"].post.requestBody.content["application/json"].schema.$ref).toBe(
      "#/components/schemas/AnswerRequest",
    );
    expect(res.body.paths["/search"].post.requestBody.content["application/json"].schema.$ref).toBe(
      "#/components/schemas/SearchRequest",
    );
    expect(res.body.paths["/search"].post.responses["200"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/SearchResponse",
    );
    expect(res.body.paths["/ingest"].post.responses["202"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/IngestResponse",
    );
    expect(
      res.body.paths["/admin/ingestion-runs/{ingestion_run_id}"].get.responses["200"].content[
        "application/json"
      ].schema.$ref,
    ).toBe("#/components/schemas/IngestionRunStatus");
    expect(res.body.paths["/admin/jobs"].get.operationId).toBe("getAdminJobs");
    expect(
      res.body.paths["/admin/sources/{source_id}/sync-status"].get.responses["200"].content[
        "application/json"
      ].schema.$ref,
    ).toBe("#/components/schemas/SourceSyncStatus");
    expect(
      res.body.paths["/admin/documents/{document_id}/processing-status"].get.operationId,
    ).toBe("getDocumentProcessingStatus");
    expect(res.body.paths["/admin/ingestion-runs/{ingestion_run_id}/retry"].post.operationId).toBe(
      "retryIngestionRun",
    );
    expect(
      res.body.paths["/admin/documents/{document_id}"].delete.responses["202"].content[
        "application/json"
      ].schema.$ref,
    ).toBe("#/components/schemas/DeleteDocumentResponse");
    expect(res.body.components.schemas.IngestResponse.properties.status.enum).toContain("dead_letter");
    expect(res.body.components.schemas.AnswerResponse.properties.status.enum).toContain(
      "insufficient_evidence",
    );
    expect(res.body.components.schemas.AnswerResponse.properties.answer_template_version.type).toBe(
      "string",
    );
    expect(res.body.components.schemas.AnswerResponse.properties.display_sections.items.required).toContain(
      "id",
    );
    expect(
      res.body.paths["/evaluations/sets"].post.requestBody.content["application/json"].schema.$ref,
    ).toBe("#/components/schemas/EvaluationSetCreateRequest");
    expect(
      res.body.paths["/evaluations/runs/{run_id}"].get.responses["200"].content["application/json"].schema.$ref,
    ).toBe("#/components/schemas/EvaluationRunStatus");
    expect(res.body.paths["/feedback"].post.responses["202"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/FeedbackResponse",
    );
    expect(res.body.paths["/industries"].get.operationId).toBe("listIndustries");
    expect(res.body.paths["/industries/{industry_id}/profile"].get.responses["200"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/IndustryProfileResponse",
    );
    expect(res.body.paths["/industries/{industry_id}/workflows/{workflow_id}/run"].post.requestBody.content["application/json"].schema.$ref).toBe(
      "#/components/schemas/IndustryWorkflowRunRequest",
    );
    expect(res.body.paths["/industries/{industry_id}/governance/status"].get.responses["200"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/IndustryGovernanceStatus",
    );
    for (const path of [
      "/manufacturing/answer",
      "/manufacturing/policy/data-use",
      "/manufacturing/governance/status",
      "/manufacturing/audit/export",
    ]) {
      expect(res.body.paths[path]).toBeDefined();
    }
    expect(res.body.paths["/manufacturing/policy/data-use"].put.requestBody.content["application/json"].schema.$ref).toBe(
      "#/components/schemas/ManufacturingDataUsePolicyPatch",
    );
    expect(res.body.paths["/manufacturing/governance/status"].get.responses["200"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/ManufacturingGovernanceStatus",
    );
    for (const path of [
      "/real-estate/metadata/import",
      "/real-estate/documents/enrich",
      "/real-estate/properties/{property_id}/knowledge",
      "/real-estate/units/{unit_id}/knowledge",
      "/real-estate/workflows/contract-question",
      "/real-estate/workflows/repair-investigation",
      "/real-estate/workflows/occupant-reply-draft",
      "/real-estate/workflows/owner-report-draft",
      "/real-estate/workflows/move-out-checklist-draft",
      "/real-estate/workflows/restoration-explanation-draft",
      "/real-estate/drafts/{artifact_id}",
      "/real-estate/drafts/{artifact_id}/review",
      "/real-estate/dashboard",
      "/real-estate/kpi",
      "/real-estate/audit",
      "/real-estate/governance/status",
    ]) {
      expect(res.body.paths[path]).toBeDefined();
    }
    expect(res.body.paths["/real-estate/metadata/import"].post.responses["202"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/RealEstateMetadataImportResponse",
    );
    expect(res.body.paths["/real-estate/governance/status"].get.responses["200"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/RealEstateGovernanceStatus",
    );
    for (const path of [
      "/investment/metadata/import",
      "/investment/documents/enrich",
      "/investment/funds/{fund_id}/knowledge",
      "/investment/workflows/fund-question",
      "/investment/workflows/rfp-response-draft",
      "/investment/workflows/ddq-response-draft",
      "/investment/workflows/inquiry-reply-draft",
      "/investment/workflows/marketing-material-check",
      "/investment/workflows/monthly-commentary-draft",
      "/investment/workflows/compliance-rule-question",
      "/investment/drafts/{artifact_id}",
      "/investment/drafts/{artifact_id}/review",
      "/investment/drafts/{artifact_id}/compliance-review",
      "/investment/disclosure-evidence/{artifact_id}",
      "/investment/dashboard",
      "/investment/kpi",
      "/investment/audit",
      "/investment/governance/status",
    ]) {
      expect(res.body.paths[path]).toBeDefined();
    }
    expect(res.body.paths["/investment/metadata/import"].post.responses["202"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/InvestmentMetadataImportResponse",
    );
    expect(res.body.paths["/investment/governance/status"].get.responses["200"].content["application/json"].schema.$ref).toBe(
      "#/components/schemas/InvestmentGovernanceStatus",
    );
  });

  it("allows the local Next.js frontend origin for credentialed answer requests", async () => {
    const res = await request(app.getHttpServer())
      .options("/v1/answer")
      .set("Origin", "http://localhost:3002")
      .set("Access-Control-Request-Method", "POST")
      .set("Access-Control-Request-Headers", "authorization,x-user-token,content-type");
    expect(res.headers["access-control-allow-origin"]).toBe("http://localhost:3002");
    expect(res.headers["access-control-allow-headers"]).toContain("x-user-token");
    expect(res.headers["access-control-expose-headers"]).toContain("api-version");
  });

  it("protected route without auth -> 401", async () => {
    const res = await request(app.getHttpServer()).get("/v1/whoami");
    expect(res.status).toBe(401);
  });

  it("protected route with Bearer + X-User-Token -> 200 + principal", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_local",
      user_id: "u1",
      groups: ["g1"],
      roles: ["reader"],
    });
    const res = await request(app.getHttpServer())
      .get("/v1/whoami")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);
    expect(res.status).toBe(200);
    expect(res.body.principal.tenant_id).toBe("tenant_local");
    expect(res.body.principal.roles).toContain("reader");
  });
});
