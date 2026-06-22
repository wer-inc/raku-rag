import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

// P1-1 — /v1/manufacturing/answer facade (e2e): auth required; tenant from the SIGNED token (never the
// body); request forwarded to the answer-service /internal/manufacturing/answer; safety fields passed
// through. The upstream is stubbed (no Postgres needed) — the safety overlay itself is verified in the
// Python answer-service tests.
describe("manufacturing answer facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let received: Record<string, unknown> | null = null;
  let receivedHeaders: http.IncomingHttpHeaders = {};
  let receivedPath = "";
  let upstreamRequestCount = 0;

  const CANNED = {
    status: "insufficient_evidence",
    text: null,
    citations: [
      {
        kind: "text",
        document_id: "press_manual",
        chunk_id: "chunk_7",
        source_id: "manuals",
        version: 3,
        retrieval_score: 0.91,
        approval_status: "approved",
        effective_date: "2026-01-10",
        approval_source: "qa-system",
      },
    ],
    used_chunks: [],
    correlation_id: "trace_mfg_stub",
    manufacturing: {
      high_risk: true,
      high_risk_reason_codes: ["disassembly"],
      safety_block_reason: "approved_citation_missing",
      obsolete_warning: false,
      requires_onsite_confirmation: true,
      notice: "作業実施前に現場責任者または有資格者の確認が必要です。",
    },
  };

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    upstream = http.createServer((req, res) => {
      upstreamRequestCount += 1;
      const url = new URL(req.url ?? "/", "http://answer-service.local");
      receivedPath = url.pathname + url.search;
      receivedHeaders = req.headers;
      let data = "";
      req.on("data", (c) => (data += c));
      req.on("end", () => {
        received = JSON.parse(data || "{}");
        res.setHeader("content-type", "application/json");
        if (req.method === "POST" && url.pathname === "/internal/manufacturing/answer") {
          res.end(JSON.stringify(CANNED));
        } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/policy/data-use") {
          res.end(
            JSON.stringify({
              tenant_id: req.headers["x-raku-tenant-id"],
              no_train_default: true,
              training_opt_in: false,
              provider_no_train_required: true,
              no_train_fallback: "block",
              retention_customer: 365,
              retention_audit: 365,
              policy_version: "1",
            }),
          );
        } else if (req.method === "PUT" && url.pathname === "/internal/manufacturing/policy/data-use") {
          const patch = received as Record<string, unknown>;
          res.end(
            JSON.stringify({
              tenant_id: req.headers["x-raku-tenant-id"],
              retention_customer: patch.retention_customer,
              policy_version: "2",
              updated_by: req.headers["x-raku-user-id"],
            }),
          );
        } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/governance/status") {
          res.end(JSON.stringify({ tenant_id: req.headers["x-raku-tenant-id"], policy_version: "1" }));
        } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/audit/export") {
          res.end(JSON.stringify({ format: url.searchParams.get("fmt") ?? "dict", records: [] }));
        } else if (
          req.method === "POST" &&
          url.pathname === "/internal/manufacturing/sources/src1/sync"
        ) {
          res.end(JSON.stringify({ ingestion_run_id: "run1", status: "queued" }));
        } else if (
          req.method === "GET" &&
          url.pathname === "/internal/manufacturing/sources/src1/sync-status"
        ) {
          res.end(JSON.stringify({ source_id: "src1", status: "queued" }));
        } else if (
          req.method === "GET" &&
          url.pathname === "/internal/manufacturing/ingestion-runs/run1"
        ) {
          res.end(JSON.stringify({ ingestion_run_id: "run1", status: "queued" }));
        } else if (
          req.method === "PUT" &&
          url.pathname === "/internal/manufacturing/documents/doc1/metadata"
        ) {
          res.end(JSON.stringify({ document_id: "doc1", manufacturing_metadata: received }));
        } else if (
          req.method === "POST" &&
          url.pathname === "/internal/manufacturing/documents/doc1/approval"
        ) {
          res.end(JSON.stringify({ document_id: "doc1", approval_state: { approval_status: "approved" } }));
        } else if (
          req.method === "POST" &&
          url.pathname === "/internal/manufacturing/trouble-cases/search"
        ) {
          res.end(JSON.stringify({ status: "insufficient_evidence", results: [], correlation_id: "trace" }));
        } else if (req.method === "POST" && url.pathname === "/internal/manufacturing/drafts") {
          res.end(JSON.stringify({ artifact_id: "art1", type: "faq", status: "draft" }));
        } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/drafts/art1") {
          res.end(JSON.stringify({ artifact_id: "art1", type: "faq", status: "draft" }));
        } else if (
          req.method === "POST" &&
          url.pathname === "/internal/manufacturing/drafts/art1/assign"
        ) {
          res.end(JSON.stringify({ artifact_id: "art1", status: "in_review" }));
        } else if (
          req.method === "POST" &&
          url.pathname === "/internal/manufacturing/drafts/art1/review"
        ) {
          res.end(JSON.stringify({ artifact_id: "art1", status: "approved" }));
        } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/dashboard") {
          res.end(JSON.stringify({ unanswered_question_count: 0 }));
        } else if (
          req.method === "GET" &&
          url.pathname === "/internal/manufacturing/safety-telemetry"
        ) {
          res.end(JSON.stringify({ high_risk_query_count: 0, safety_gate_block_count: 0 }));
        } else if (req.method === "GET" && url.pathname === "/internal/manufacturing/kpi") {
          res.end(JSON.stringify({ grounded_answer_rate: 1 }));
        } else {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: "wrong upstream route" }));
        }
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
  });

  it("POST /v1/manufacturing/answer without auth -> 401", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/manufacturing/answer")
      .send({ query: "x" });
    expect(res.status).toBe(401);
  });

  it("forwards to the answer-service with the signed principal and passes safety fields through", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "op",
      groups: ["ops"],
      roles: ["reader"],
    });
    const res = await request(app.getHttpServer())
      .post("/v1/manufacturing/answer")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      // a body-supplied tenant_id must be IGNORED (tenant comes from the signed token)
      .send({ tenant_id: "tenant_evil", query: "How do I disassemble the press safely?" });

    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/answer");
    expect(received?.tenant_id).toBe("tenant_a");
    expect(received?.query).toBe("How do I disassemble the press safely?");
    expect(res.body.status).toBe("insufficient_evidence");
    expect(res.body.manufacturing.high_risk).toBe(true);
    expect(res.body.manufacturing.safety_block_reason).toBe("approved_citation_missing");
    expect(res.body.citations[0].approval_status).toBe("approved");
    expect(res.body.citations[0].effective_date).toBe("2026-01-10");
  });

  it("GET /v1/manufacturing/policy/data-use forwards the signed principal", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "admin",
      groups: ["ops"],
      roles: ["admin"],
    });
    const res = await request(app.getHttpServer())
      .get("/v1/manufacturing/policy/data-use")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/policy/data-use");
    expect(receivedHeaders["x-raku-tenant-id"]).toBe("tenant_a");
    expect(res.body.no_train_fallback).toBe("block");
  });

  it("PUT /v1/manufacturing/policy/data-use strips body tenant overrides", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "admin",
      groups: ["ops"],
      roles: ["admin"],
    });
    const res = await request(app.getHttpServer())
      .put("/v1/manufacturing/policy/data-use")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ tenant_id: "tenant_evil", retention_customer: 730 });

    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/policy/data-use");
    expect(received?.tenant_id).toBeUndefined();
    expect(receivedHeaders["x-raku-tenant-id"]).toBe("tenant_a");
    expect(res.body.retention_customer).toBe(730);
    expect(res.body.updated_by).toBe("admin");
  });

  it("rejects non-admin data-use policy mutations before forwarding", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "reader",
      groups: ["ops"],
      roles: ["reader"],
    });
    const before = upstreamRequestCount;

    const res = await request(app.getHttpServer())
      .put("/v1/manufacturing/policy/data-use")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ retention_customer: 30 });

    expect(res.status).toBe(403);
    expect(upstreamRequestCount).toBe(before);
  });

  it("forwards governance status and audit export reads", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "admin",
      groups: ["ops"],
      roles: ["admin"],
    });

    const status = await request(app.getHttpServer())
      .get("/v1/manufacturing/governance/status")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);
    expect(status.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/governance/status");

    const audit = await request(app.getHttpServer())
      .get("/v1/manufacturing/audit/export?fmt=dict")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);
    expect(audit.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/audit/export?fmt=dict");
    expect(audit.body.records).toEqual([]);
  });

  it("forwards the remaining manufacturing contract routes through the facade", async () => {
    const adminToken = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "admin",
      groups: ["ops"],
      roles: ["admin"],
    });
    const readerToken = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "reader",
      groups: ["ops"],
      roles: ["reader"],
    });

    const authed = (token: string) => ({
      Authorization: "Bearer local-dev-key",
      "X-User-Token": token,
    });

    let res = await request(app.getHttpServer())
      .post("/v1/manufacturing/sources/src1/sync")
      .set(authed(adminToken))
      .send({ collection_id: "c" });
    expect(res.status).toBe(202);
    expect(receivedPath).toBe("/internal/manufacturing/sources/src1/sync");

    res = await request(app.getHttpServer())
      .get("/v1/manufacturing/sources/src1/sync-status")
      .set(authed(readerToken));
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/sources/src1/sync-status");

    res = await request(app.getHttpServer())
      .get("/v1/manufacturing/ingestion-runs/run1")
      .set(authed(readerToken));
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/ingestion-runs/run1");

    res = await request(app.getHttpServer())
      .put("/v1/manufacturing/documents/doc1/metadata")
      .set(authed(adminToken))
      .send({ tenant_id: "tenant_evil", manufacturing_metadata: { document_type: "training" } });
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/documents/doc1/metadata");
    expect(received?.tenant_id).toBeUndefined();

    res = await request(app.getHttpServer())
      .post("/v1/manufacturing/documents/doc1/approval")
      .set(authed(adminToken))
      .send({ to_status: "approved" });
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/documents/doc1/approval");

    res = await request(app.getHttpServer())
      .post("/v1/manufacturing/trouble-cases/search")
      .set(authed(readerToken))
      .send({ symptom_query: "振動" });
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/trouble-cases/search");

    res = await request(app.getHttpServer())
      .post("/v1/manufacturing/drafts")
      .set(authed(readerToken))
      .send({ kind: "faq" });
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/drafts");
    expect(res.body.status).toBe("draft");

    res = await request(app.getHttpServer())
      .get("/v1/manufacturing/drafts/art1")
      .set(authed(readerToken));
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/drafts/art1");

    res = await request(app.getHttpServer())
      .post("/v1/manufacturing/drafts/art1/assign")
      .set(authed(adminToken))
      .send({ reviewer_id: "sme1" });
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/drafts/art1/assign");

    res = await request(app.getHttpServer())
      .post("/v1/manufacturing/drafts/art1/review")
      .set(authed(adminToken))
      .send({ decision: "approved" });
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/drafts/art1/review");

    res = await request(app.getHttpServer())
      .get("/v1/manufacturing/dashboard?collection_id=c")
      .set(authed(readerToken));
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/dashboard?collection_id=c");

    res = await request(app.getHttpServer())
      .get("/v1/manufacturing/safety-telemetry?granularity=daily")
      .set(authed(readerToken));
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/safety-telemetry?granularity=daily");

    res = await request(app.getHttpServer())
      .get("/v1/manufacturing/kpi?format=json")
      .set(authed(readerToken));
    expect(res.status).toBe(200);
    expect(receivedPath).toBe("/internal/manufacturing/kpi?format=json");
  });
});
