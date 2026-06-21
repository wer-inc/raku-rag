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
  let receivedPath = "";

  const CANNED = {
    status: "insufficient_evidence",
    text: null,
    citations: [],
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
      receivedPath = req.url ?? "";
      let data = "";
      req.on("data", (c) => (data += c));
      req.on("end", () => {
        received = JSON.parse(data || "{}");
        res.setHeader("content-type", "application/json");
        if (req.method !== "POST" || receivedPath !== "/internal/manufacturing/answer") {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: "wrong upstream route" }));
          return;
        }
        res.end(JSON.stringify(CANNED));
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
  });
});
