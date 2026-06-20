import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("investment facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let previousAnswerServiceUrl: string | undefined;
  const seen: Array<{
    method: string | undefined;
    url: string | undefined;
    tenant: string | string[] | undefined;
    body: any;
  }> = [];

  const token = makeUserToken({
    tenant_id: "tenant_im",
    user_id: "fund_ops_1",
    groups: ["investment"],
    roles: ["admin"],
  });

  function send(res: http.ServerResponse, status: number, payload: unknown) {
    res.statusCode = status;
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify(payload));
  }

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    previousAnswerServiceUrl = process.env.ANSWER_SERVICE_URL;
    upstream = http.createServer((req, res) => {
      const chunks: Buffer[] = [];
      req.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
      req.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        const body = raw ? JSON.parse(raw) : undefined;
        seen.push({ method: req.method, url: req.url, tenant: req.headers["x-raku-tenant-id"], body });

        if (req.method === "POST" && req.url === "/internal/investment/metadata/import") {
          send(res, 202, { import_run_id: "im_import", accepted_count: 1, rejected_count: 0, status_url: "/v1/investment/audit" });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/documents/enrich") {
          send(res, 200, { document_id: "prospectus_001", investment_metadata: { fund_id: "FUND-001" }, normalized_aliases: {}, warnings: [] });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/investment/funds/FUND-001/knowledge") {
          send(res, 200, { fund_id: "FUND-001", documents: [{ document_id: "prospectus_001" }], citations: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/workflows/fund-question") {
          send(res, 200, { status: "ok", answer: "ファンド回答", citations: [], review_required: true });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/workflows/rfp-response-draft") {
          send(res, 201, { artifact_id: "draft_rfp", artifact_type: "rfp_response", status: "draft", compliance_review_status: "pending", source_citations: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/workflows/ddq-response-draft") {
          send(res, 201, { artifact_id: "draft_ddq", artifact_type: "ddq_response", status: "draft", compliance_review_status: "pending", source_citations: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/workflows/inquiry-reply-draft") {
          send(res, 201, { artifact_id: "draft_inq", artifact_type: "inquiry_reply", status: "draft", compliance_review_status: "pending", source_citations: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/workflows/marketing-material-check") {
          send(res, 200, { artifact_id: "draft_mkt", artifact_type: "marketing_material_comment", status: "draft", contradiction_results: [{}], disclosure_evidence_ids: ["disc_1"] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/workflows/monthly-commentary-draft") {
          send(res, 201, { artifact_id: "draft_monthly", artifact_type: "monthly_commentary", status: "draft", compliance_review_status: "pending", source_citations: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/workflows/compliance-rule-question") {
          send(res, 200, { status: "ok", answer: "規程回答", citations: [], review_required: true });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/investment/drafts/draft_rfp") {
          send(res, 200, { artifact_id: "draft_rfp", artifact_type: "rfp_response", status: "draft", compliance_review_status: "pending" });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/drafts/draft_rfp/review") {
          send(res, 200, { artifact_id: "draft_rfp", status: "in_review" });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/investment/drafts/draft_rfp/compliance-review") {
          send(res, 200, { artifact_id: "draft_rfp", compliance_review_status: "pending" });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/investment/disclosure-evidence/draft_rfp") {
          send(res, 200, { artifact_id: "draft_rfp", evidence: [{ disclosure_evidence_id: "disc_1" }] });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/investment/dashboard") {
          send(res, 200, { widgets: [{ widget_id: "regulated_query_count" }], warnings: [] });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/investment/kpi") {
          send(res, 200, { regulated_query_count: 1, compliance_review_pending_count: 1 });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/investment/audit") {
          send(res, 200, { events: [{ event_type: "investment_metadata_import" }] });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/investment/governance/status") {
          send(res, 200, { poc_readiness: "ready", compliance_review: { auto_approval: false } });
          return;
        }
        send(res, 404, { error: "not found" });
      });
    });
    await new Promise<void>((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    process.env.ANSWER_SERVICE_URL = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`;
    app = await createApp();
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    await new Promise<void>((resolve) => upstream.close(() => resolve()));
    process.env.ANSWER_SERVICE_URL = previousAnswerServiceUrl;
  });

  it("requires auth", async () => {
    const res = await request(app.getHttpServer()).get("/v1/investment/dashboard");
    expect(res.status).toBe(401);
  });

  it("forwards metadata import and strips tenant overrides", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/investment/metadata/import")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ tenant_id: "tenant_victim", records: [{ metadata: { tenant_id: "tenant_victim", fund_id: "FUND-001" } }] });
    expect(res.status).toBe(202);
    expect(res.body.accepted_count).toBe(1);
    expect(seen.at(-1)?.tenant).toBe("tenant_im");
    expect(seen.at(-1)?.body.tenant_id).toBeUndefined();
    expect(seen.at(-1)?.body.records[0].metadata.tenant_id).toBeUndefined();
  });

  it("proxies every investment contract endpoint", async () => {
    const auth = (req: request.Test) => req.set("Authorization", "Bearer local-dev-key").set("X-User-Token", token);
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/documents/enrich")).send({ document_id: "prospectus_001" })).status).toBe(200);
    expect((await auth(request(app.getHttpServer()).get("/v1/investment/funds/FUND-001/knowledge"))).status).toBe(200);
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/workflows/fund-question")).send({ question: "信託報酬" })).body.status).toBe("ok");
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/workflows/rfp-response-draft")).send({ question: "運用体制" })).body.artifact_type).toBe("rfp_response");
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/workflows/ddq-response-draft")).send({ question: "ESG" })).body.artifact_type).toBe("ddq_response");
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/workflows/inquiry-reply-draft")).send({ inquiry_text: "商品概要" })).body.artifact_type).toBe("inquiry_reply");
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/workflows/marketing-material-check")).send({ statements: ["過去実績"] })).body.artifact_type).toBe("marketing_material_comment");
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/workflows/monthly-commentary-draft")).send({ fund_id: "FUND-001" })).body.artifact_type).toBe("monthly_commentary");
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/workflows/compliance-rule-question")).send({ question: "広告審査" })).body.status).toBe("ok");
    expect((await auth(request(app.getHttpServer()).get("/v1/investment/drafts/draft_rfp"))).body.status).toBe("draft");
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/drafts/draft_rfp/review")).send({ action: "submit" })).body.status).toBe("in_review");
    expect((await auth(request(app.getHttpServer()).post("/v1/investment/drafts/draft_rfp/compliance-review")).send({ action: "approve" })).body.compliance_review_status).toBe("pending");
    expect((await auth(request(app.getHttpServer()).get("/v1/investment/disclosure-evidence/draft_rfp"))).body.evidence[0].disclosure_evidence_id).toBe("disc_1");
    expect((await auth(request(app.getHttpServer()).get("/v1/investment/dashboard"))).body.widgets[0].widget_id).toBe("regulated_query_count");
    expect((await auth(request(app.getHttpServer()).get("/v1/investment/kpi"))).body.regulated_query_count).toBe(1);
    expect((await auth(request(app.getHttpServer()).get("/v1/investment/audit"))).body.events[0].event_type).toBe("investment_metadata_import");
    expect((await auth(request(app.getHttpServer()).get("/v1/investment/governance/status"))).body.poc_readiness).toBe("ready");
  });
});
