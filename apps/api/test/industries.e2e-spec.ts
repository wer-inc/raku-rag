import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("industries facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let previousAnswerServiceUrl: string | undefined;
  const seen: Array<{
    method: string | undefined;
    url: string | undefined;
    tenant: string | string[] | undefined;
    user: string | string[] | undefined;
    body: any;
  }> = [];

  const token = makeUserToken({
    tenant_id: "tenant_industry",
    user_id: "operator_1",
    groups: ["pm"],
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
        seen.push({
          method: req.method,
          url: req.url,
          tenant: req.headers["x-raku-tenant-id"],
          user: req.headers["x-raku-user-id"],
          body,
        });

        if (req.method === "GET" && req.url === "/internal/industries") {
          send(res, 200, {
            industries: [{ industry_id: "real_estate_pm", name: "Real Estate", status: "active", version: 1 }],
          });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/industries/real_estate_pm/profile") {
          send(res, 200, {
            industry_id: "real_estate_pm",
            version: 1,
            workflows: [{ workflow_id: "contract_question" }],
          });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/industries/real_estate_pm/metadata/validate") {
          send(res, 200, { valid: true, errors: [], industry_id: "real_estate_pm" });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/industries/real_estate_pm/workflows/contract_question/run") {
          send(res, 200, { status: "ok", text: "answered", industry_id: "real_estate_pm" });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/industries/real_estate_pm/dashboard") {
          send(res, 200, { widgets: [{ widget_id: "real_estate_pm_overview" }], denied_widget_ids: [] });
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

  it("GET /v1/industries without auth -> 401", async () => {
    const res = await request(app.getHttpServer()).get("/v1/industries");
    expect(res.status).toBe(401);
  });

  it("GET /v1/industries forwards signed principal headers", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/industries")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body.industries[0].industry_id).toBe("real_estate_pm");
    expect(seen.at(-1)?.method).toBe("GET");
    expect(seen.at(-1)?.url).toBe("/internal/industries");
    expect(seen.at(-1)?.tenant).toBe("tenant_industry");
  });

  it("GET /v1/industries/:id/profile proxies the generic profile contract", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/industries/real_estate_pm/profile")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body.workflows[0].workflow_id).toBe("contract_question");
    expect(seen.at(-1)?.url).toBe("/internal/industries/real_estate_pm/profile");
  });

  it("POST metadata validation strips body tenant overrides", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/industries/real_estate_pm/metadata/validate")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ tenant_id: "tenant_victim", metadata: { tenant_id: "tenant_victim", document_id: "d1" } });

    expect(res.status).toBe(200);
    expect(seen.at(-1)?.tenant).toBe("tenant_industry");
    expect(seen.at(-1)?.body.tenant_id).toBeUndefined();
    expect(seen.at(-1)?.body.metadata.tenant_id).toBeUndefined();
  });

  it("POST workflow run forwards to the specific industry workflow endpoint", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/industries/real_estate_pm/workflows/contract_question/run")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ query: "契約上ペットは可能ですか" });

    expect(res.status).toBe(200);
    expect(res.body.status).toBe("ok");
    expect(seen.at(-1)?.url).toBe("/internal/industries/real_estate_pm/workflows/contract_question/run");
    expect(seen.at(-1)?.user).toBe("operator_1");
  });

  it("GET dashboard exposes tenant-filtered industry dashboard response", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/industries/real_estate_pm/dashboard")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body.widgets[0].widget_id).toBe("real_estate_pm_overview");
  });
});
