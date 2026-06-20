import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("real estate facade (e2e)", () => {
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
    tenant_id: "tenant_re",
    user_id: "pm_1",
    groups: ["property"],
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

        if (req.method === "POST" && req.url === "/internal/real-estate/metadata/import") {
          send(res, 202, { import_run_id: "re_import", accepted_count: 1, rejected_count: 0, status_url: "/v1/real-estate/audit" });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/real-estate/documents/enrich") {
          send(res, 200, { document_id: "lease_305", real_estate_metadata: { property_id: "P001" }, warnings: [] });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/real-estate/properties/P001/knowledge") {
          send(res, 200, { property_id: "P001", documents: [{ document_id: "lease_305" }], citations: [] });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/real-estate/units/U305/knowledge") {
          send(res, 200, { unit_id: "U305", lease_contracts: [], repair_cases: [], inquiries: [], documents: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/real-estate/workflows/contract-question") {
          send(res, 200, { status: "ok", answer: "契約回答", citations: [], review_required: true });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/real-estate/workflows/repair-investigation") {
          send(res, 200, { status: "ok", similar_cases: [], summary: "修繕履歴", citations: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/real-estate/workflows/occupant-reply-draft") {
          send(res, 201, { artifact_id: "draft_occ", artifact_type: "occupant_reply", status: "draft", source_citations: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/real-estate/workflows/owner-report-draft") {
          send(res, 201, { artifact_id: "draft_owner", artifact_type: "owner_report", status: "draft", source_citations: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/real-estate/workflows/move-out-checklist-draft") {
          send(res, 201, { artifact_id: "draft_move", artifact_type: "move_out_checklist", status: "draft", source_citations: [] });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/real-estate/workflows/restoration-explanation-draft") {
          send(res, 201, { artifact_id: "draft_rest", artifact_type: "restoration_explanation", status: "draft", source_citations: [] });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/real-estate/drafts/draft_occ") {
          send(res, 200, { artifact_id: "draft_occ", artifact_type: "occupant_reply", status: "draft" });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/real-estate/drafts/draft_occ/review") {
          send(res, 200, { artifact_id: "draft_occ", status: "in_review" });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/real-estate/dashboard") {
          send(res, 200, { widgets: [{ widget_id: "repair_case_lookup_count" }], warnings: [] });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/real-estate/kpi") {
          send(res, 200, { repair_case_lookup_count: 1, owner_report_draft_count: 1 });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/real-estate/audit") {
          send(res, 200, { events: [{ event_type: "real_estate_metadata_import" }] });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/real-estate/governance/status") {
          send(res, 200, { poc_readiness: "ready", draft_review: { auto_approval: false } });
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
    const res = await request(app.getHttpServer()).get("/v1/real-estate/dashboard");
    expect(res.status).toBe(401);
  });

  it("forwards metadata import and strips tenant overrides", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/real-estate/metadata/import")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ tenant_id: "tenant_victim", records: [{ metadata: { tenant_id: "tenant_victim", property_id: "P001" } }] });
    expect(res.status).toBe(202);
    expect(res.body.accepted_count).toBe(1);
    expect(seen.at(-1)?.tenant).toBe("tenant_re");
    expect(seen.at(-1)?.body.tenant_id).toBeUndefined();
    expect(seen.at(-1)?.body.records[0].metadata.tenant_id).toBeUndefined();
  });

  it("proxies every real estate contract endpoint", async () => {
    const auth = (req: request.Test) => req.set("Authorization", "Bearer local-dev-key").set("X-User-Token", token);
    expect((await auth(request(app.getHttpServer()).post("/v1/real-estate/documents/enrich")).send({ document_id: "lease_305" })).status).toBe(200);
    expect((await auth(request(app.getHttpServer()).get("/v1/real-estate/properties/P001/knowledge"))).status).toBe(200);
    expect((await auth(request(app.getHttpServer()).get("/v1/real-estate/units/U305/knowledge"))).status).toBe(200);
    expect((await auth(request(app.getHttpServer()).post("/v1/real-estate/workflows/contract-question")).send({ question: "契約上ペットは可能ですか" })).body.status).toBe("ok");
    expect((await auth(request(app.getHttpServer()).post("/v1/real-estate/workflows/repair-investigation")).send({ symptom: "水漏れ" })).body.status).toBe("ok");
    expect((await auth(request(app.getHttpServer()).post("/v1/real-estate/workflows/occupant-reply-draft")).send({ inquiry_text: "水漏れ" })).body.artifact_type).toBe("occupant_reply");
    expect((await auth(request(app.getHttpServer()).post("/v1/real-estate/workflows/owner-report-draft")).send({ property_id: "P001" })).body.artifact_type).toBe("owner_report");
    expect((await auth(request(app.getHttpServer()).post("/v1/real-estate/workflows/move-out-checklist-draft")).send({ unit_id: "U305" })).body.artifact_type).toBe("move_out_checklist");
    expect((await auth(request(app.getHttpServer()).post("/v1/real-estate/workflows/restoration-explanation-draft")).send({ unit_id: "U305" })).body.artifact_type).toBe("restoration_explanation");
    expect((await auth(request(app.getHttpServer()).get("/v1/real-estate/drafts/draft_occ"))).body.status).toBe("draft");
    expect((await auth(request(app.getHttpServer()).post("/v1/real-estate/drafts/draft_occ/review")).send({ action: "submit" })).body.status).toBe("in_review");
    expect((await auth(request(app.getHttpServer()).get("/v1/real-estate/dashboard"))).body.widgets[0].widget_id).toBe("repair_case_lookup_count");
    expect((await auth(request(app.getHttpServer()).get("/v1/real-estate/kpi"))).body.repair_case_lookup_count).toBe(1);
    expect((await auth(request(app.getHttpServer()).get("/v1/real-estate/audit"))).body.events[0].event_type).toBe("real_estate_metadata_import");
    expect((await auth(request(app.getHttpServer()).get("/v1/real-estate/governance/status"))).body.poc_readiness).toBe("ready");
  });
});
