import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

// Tier D — `/v1/answer` facade contract. In the manufacturing product this legacy route is a
// compatibility alias for the safety-aware answer-service path, so older clients cannot bypass the
// manufacturing safety overlay. A stub stands in for the Python answer-service so this asserts the
// FACADE behaviour (auth required; identity taken from the signed token, NOT the body; request
// forwarded; response passed through) with no Postgres. RAG correctness itself is the Tier B parity gate.
describe("answer facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let received: Record<string, unknown> | null = null;
  let receivedMethod = "";
  let receivedPath = "";
  const CANNED = {
    status: "ok",
    text: "stub answer",
    citations: [
      { kind: "text", document_id: "d1", chunk_id: "d1:0", source_id: "src", version: 1, text_range: [0, 3], retrieval_score: 0.9 },
    ],
    used_chunks: [{ chunk_id: "d1:0", document_id: "d1", retrieval_score: 0.0 }],
    confidence: 0.9,
    freshness: null,
    correlation_id: "trace_stub",
    manufacturing: {
      high_risk: false,
      high_risk_reason_codes: [],
      safety_block_reason: null,
      obsolete_warning: false,
      requires_onsite_confirmation: false,
      notice: null,
    },
  };

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    upstream = http.createServer((req, res) => {
      receivedMethod = req.method ?? "";
      receivedPath = req.url ?? "";
      let data = "";
      req.on("data", (c) => (data += c));
      req.on("end", () => {
        received = JSON.parse(data || "{}");
        res.setHeader("content-type", "application/json");
        if (receivedMethod !== "POST" || receivedPath !== "/internal/manufacturing/answer") {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: "wrong upstream route" }));
          return;
        }
        res.end(JSON.stringify(CANNED));
      });
    });
    await new Promise<void>((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    const port = (upstream.address() as AddressInfo).port;
    process.env.ANSWER_SERVICE_URL = `http://127.0.0.1:${port}`;
    app = await createApp();
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    await new Promise<void>((resolve) => upstream.close(() => resolve()));
  });

  it("POST /v1/answer without auth -> 401", async () => {
    const res = await request(app.getHttpServer()).post("/v1/answer").send({ query: "x" });
    expect(res.status).toBe(401);
  });

  it("POST /v1/answer forwards the query and passes through the answer-service response", async () => {
    const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: ["ops"], roles: ["reader"] });
    const res = await request(app.getHttpServer())
      .post("/v1/answer")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ query: "maintenance interval" });

    expect(res.status).toBe(200);
    expect(res.body.status).toBe("ok");
    expect(res.body.text).toBe("stub answer");
    expect(res.body.citations[0].document_id).toBe("d1");
    // forwarded the query + the principal's identity to the answer-service
    expect(received?.query).toBe("maintenance interval");
    expect(received?.tenant_id).toBe("tenant_a");
    expect(received?.user_id).toBe("alice");
    expect(receivedMethod).toBe("POST");
    expect(receivedPath).toBe("/internal/manufacturing/answer");
    expect(res.body.manufacturing.high_risk).toBe(false);
  });

  it("SECURITY: tenant comes from the signed token, never from the request body", async () => {
    const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: [], roles: [] });
    const res = await request(app.getHttpServer())
      .post("/v1/answer")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      // attacker attempts to override the tenant via the body:
      .send({ query: "x", tenant_id: "tenant_victim" });

    expect(res.status).toBe(200);
    expect(received?.tenant_id).toBe("tenant_a"); // body tenant_id is ignored
  });

  it("502 when the answer-service is unreachable", async () => {
    const saved = process.env.ANSWER_SERVICE_URL;
    process.env.ANSWER_SERVICE_URL = "http://127.0.0.1:1"; // nothing listening
    try {
      const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: [], roles: [] });
      const res = await request(app.getHttpServer())
        .post("/v1/answer")
        .set("Authorization", "Bearer local-dev-key")
        .set("X-User-Token", token)
        .send({ query: "x" });
      expect(res.status).toBe(502);
    } finally {
      process.env.ANSWER_SERVICE_URL = saved;
    }
  });
});
