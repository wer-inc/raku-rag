import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("MVP completion facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let receivedPath = "";

  const adminToken = makeUserToken({
    tenant_id: "tenant_a",
    user_id: "alice",
    groups: [],
    roles: ["tenant_admin"],
  });

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    upstream = http.createServer((req, res) => {
      const url = new URL(req.url ?? "/", "http://answer-service.local");
      receivedPath = url.pathname + url.search;
      res.setHeader("content-type", "application/json");
      if (req.method === "GET" && url.pathname === "/internal/manufacturing/drafts") {
        res.end(JSON.stringify({ drafts: [{ artifact_id: "art1", status: "draft" }] }));
      } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/documents") {
        res.end(JSON.stringify({ documents: [{ document_id: "doc1", approval_status: "pending_review" }] }));
      } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/documents/doc1") {
        res.end(JSON.stringify({ document_id: "doc1", chunks: [{ chunk_id: "c1", text: "body" }] }));
      } else if (req.method === "GET" && url.pathname === "/internal/documents/doc1/citation-view") {
        res.end(JSON.stringify({ document_id: "doc1", preview: { kind: "text" }, chunks: [] }));
      } else if (req.method === "GET" && url.pathname === "/internal/documents/doc1/file") {
        res.end(JSON.stringify({ document_id: "doc1", content_type: "text/plain", size: 4, content_base64: "dGVzdA==" }));
      } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/audit/events") {
        res.end(JSON.stringify({ events: [], total: 0, offset: 0, limit: 100 }));
      } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/improvements") {
        res.end(JSON.stringify({ items: [{ id: "imp1", kind: "low_rating" }], total: 1, correlation_id: "x" }));
      } else {
        res.statusCode = 500;
        res.end(JSON.stringify({ error: "unexpected route", path: receivedPath }));
      }
    });
    await new Promise<void>((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    process.env.ANSWER_SERVICE_URL = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`;
    app = await createApp();
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    await new Promise<void>((resolve) => upstream.close(() => resolve()));
  });

  it("GET /v1/manufacturing/drafts lists drafts", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/manufacturing/drafts")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken);
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/drafts");
    expect(res.body.drafts[0].artifact_id).toBe("art1");
  });

  it("GET /v1/admin/documents returns inventory", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/admin/documents?approval_status=pending_review")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken);
    expect(res.status).toBe(200);
    expect(receivedPath).toContain("/internal/manufacturing/documents");
    expect(res.body.documents[0].document_id).toBe("doc1");
  });

  it("GET /v1/admin/documents/:id/citation-view returns preview payload", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/admin/documents/doc1/citation-view?chunk_id=c1")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken);
    expect(res.status).toBe(200);
    expect(receivedPath).toContain("/internal/documents/doc1/citation-view");
    expect(res.body.preview.kind).toBe("text");
  });

  it("GET /v1/manufacturing/improvements returns queue items", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/manufacturing/improvements")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken);
    expect(res.status).toBe(200);
    expect(receivedPath).toContain("/internal/manufacturing/improvements");
    expect(res.body.items[0].kind).toBe("low_rating");
  });

  it("GET /v1/manufacturing/audit/events returns paginated events", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/manufacturing/audit/events?limit=10")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken);
    expect(res.status).toBe(200);
    expect(receivedPath).toContain("/internal/manufacturing/audit/events");
    expect(res.body.total).toBe(0);
  });
});
