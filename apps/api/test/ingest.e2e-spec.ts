import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("ingest facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let received: Record<string, unknown> | null = null;
  const previousUploadBucket = process.env.RAKU_UPLOAD_BUCKET;

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    process.env.RAKU_UPLOAD_BUCKET = "bucket";
    upstream = http.createServer((req, res) => {
      let data = "";
      req.on("data", (c) => (data += c));
      req.on("end", () => {
        received = JSON.parse(data || "{}");
        res.setHeader("content-type", "application/json");
        if (req.method !== "POST" || req.url !== "/internal/ingest") {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: "wrong upstream route" }));
          return;
        }
        res.end(
          JSON.stringify({
            ingestion_run_id: "ing_stub",
            document_id: String(received?.document_id ?? ""),
            status: "succeeded",
            status_url: "/v1/admin/ingestion-runs/ing_stub",
            chunk_count: 1,
          }),
        );
      });
    });
    await new Promise<void>((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    process.env.ANSWER_SERVICE_URL = `http://127.0.0.1:${(upstream.address() as AddressInfo).port}`;
    app = await createApp();
    await app.init();
  });

  beforeEach(() => {
    received = null;
  });

  afterAll(async () => {
    if (previousUploadBucket === undefined) {
      delete process.env.RAKU_UPLOAD_BUCKET;
    } else {
      process.env.RAKU_UPLOAD_BUCKET = previousUploadBucket;
    }
    await app?.close();
    await new Promise<void>((resolve) => upstream.close(() => resolve()));
  });

  it("POST /v1/ingest without auth -> 401", async () => {
    const res = await request(app.getHttpServer()).post("/v1/ingest").send({});
    expect(res.status).toBe(401);
  });

  it("POST /v1/ingest forwards tenant from token and returns accepted status", async () => {
    const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: ["ops"], roles: ["writer"] });
    const res = await request(app.getHttpServer())
      .post("/v1/ingest")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        tenant_id: "attacker_override",
        collection_id: "manuals",
        source_id: "upload",
        document_id: "doc1",
        ref: "s3://bucket/tenants/tenant_a/uploads/2026-06-29/doc1.txt",
        content_type: "text/plain",
      });

    expect(res.status).toBe(202);
    expect(res.body.status).toBe("succeeded");
    expect(received?.tenant_id).toBe("tenant_a");
    expect(received?.user_id).toBe("alice");
    expect(received?.document_ref).toBe("s3://bucket/tenants/tenant_a/uploads/2026-06-29/doc1.txt");
    expect(received?.document_id).toBe("doc1");
  });

  it("POST /v1/ingest rejects S3 refs owned by another tenant before forwarding", async () => {
    const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: ["ops"], roles: ["writer"] });
    const res = await request(app.getHttpServer())
      .post("/v1/ingest")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        collection_id: "manuals",
        source_id: "upload",
        document_id: "doc1",
        ref: "s3://bucket/tenants/tenant_b/uploads/2026-06-29/doc1.txt",
        content_type: "text/plain",
      });

    expect(res.status).toBe(403);
    expect(received).toBeNull();
  });

  it("POST /v1/ingest rejects S3 refs outside the configured upload bucket", async () => {
    const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: ["ops"], roles: ["writer"] });
    const res = await request(app.getHttpServer())
      .post("/v1/ingest")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        collection_id: "manuals",
        source_id: "upload",
        document_id: "doc1",
        ref: "s3://other-bucket/tenants/tenant_a/uploads/2026-06-29/doc1.txt",
        content_type: "text/plain",
      });

    expect(res.status).toBe(403);
    expect(received).toBeNull();
  });

  it("POST /v1/ingest rejects S3 refs without the tenant upload prefix", async () => {
    const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: ["ops"], roles: ["writer"] });
    const res = await request(app.getHttpServer())
      .post("/v1/ingest")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        collection_id: "manuals",
        source_id: "upload",
        document_id: "doc1",
        ref: "s3://bucket/web-uploads/prod/2026-06-29/doc1.txt",
        content_type: "text/plain",
      });

    expect(res.status).toBe(403);
    expect(received).toBeNull();
  });
});
