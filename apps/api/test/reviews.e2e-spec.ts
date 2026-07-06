import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

/** ADR-018 §12 — extraction review queue facade (e2e). Stubs the answer-service upstream. */
describe("extraction review facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let previousAnswerServiceUrl: string | undefined;
  const seen: Array<{ method: string | undefined; url: string | undefined; tenant: string | string[] | undefined }> = [];

  const adminToken = makeUserToken({
    tenant_id: "tenant_admin",
    user_id: "reviewer",
    groups: ["platform"],
    roles: ["admin"],
  });
  const readerToken = makeUserToken({
    tenant_id: "tenant_admin",
    user_id: "reader",
    groups: ["platform"],
    roles: ["reader"],
  });

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    previousAnswerServiceUrl = process.env.ANSWER_SERVICE_URL;
    upstream = http.createServer((req, res) => {
      seen.push({ method: req.method, url: req.url, tenant: req.headers["x-raku-tenant-id"] });
      res.setHeader("content-type", "application/json");
      if (req.method === "GET" && req.url === "/internal/reviews/extraction") {
        res.end(
          JSON.stringify({
            items: [
              { tenant_id: "tenant_admin", document_id: "broken", chunk_id: "broken:0", status: "review_required", reasons: ["mojibake_suspected"] },
            ],
          }),
        );
        return;
      }
      if (req.method === "GET" && req.url === "/internal/reviews/extraction/metrics") {
        res.end(JSON.stringify({ total: 2, by_status: { accepted: 1, review_required: 1 }, quarantine_rate: 0.5 }));
        return;
      }
      if (req.method === "POST" && req.url === "/internal/reviews/extraction/actions") {
        res.end(JSON.stringify({ chunk_id: "broken:0", action: "approve", status: "manual_approved", reviewed_by: "reviewer" }));
        return;
      }
      res.statusCode = 500;
      res.end(JSON.stringify({ error: "wrong upstream route" }));
    });
    await new Promise<void>((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    process.env.ANSWER_SERVICE_URL = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`;
    app = await createApp();
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    await new Promise<void>((resolve) => upstream.close(() => resolve()));
    if (previousAnswerServiceUrl === undefined) {
      delete process.env.ANSWER_SERVICE_URL;
    } else {
      process.env.ANSWER_SERVICE_URL = previousAnswerServiceUrl;
    }
  });

  it("requires auth", async () => {
    const res = await request(app.getHttpServer()).get("/v1/reviews/extraction");
    expect(res.status).toBe(401);
  });

  it("GET /v1/reviews/extraction returns the tenant queue with signed principal headers", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/reviews/extraction")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken);
    expect(res.status).toBe(200);
    expect(res.body.items[0].document_id).toBe("broken");
    expect(seen[seen.length - 1].tenant).toBe("tenant_admin");
  });

  it("GET /v1/reviews/extraction/metrics returns the ops snapshot", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/reviews/extraction/metrics")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken);
    expect(res.status).toBe(200);
    expect(res.body.quarantine_rate).toBe(0.5);
  });

  it("POST /v1/reviews/extraction/actions applies a decision (admin)", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/reviews/extraction/actions")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken)
      .send({ chunk_id: "broken:0", action: "approve" });
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("manual_approved");
  });

  it("rejects a non-admin applying a review action (never reaches the core)", async () => {
    const before = seen.length;
    const res = await request(app.getHttpServer())
      .post("/v1/reviews/extraction/actions")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", readerToken)
      .send({ chunk_id: "broken:0", action: "approve" });
    expect(res.status).toBe(403);
    expect(seen.length).toBe(before);
  });
});
