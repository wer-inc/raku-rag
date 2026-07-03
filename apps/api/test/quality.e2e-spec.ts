import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

// ★G3b/★G5: the 実測運用メトリクス facade — reviewer/admin-gated, tenant from the principal.
describe("quality operational facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let previousAnswerServiceUrl: string | undefined;
  const seen: Array<{ method: string | undefined; url: string | undefined; tenant: string | string[] | undefined }> = [];

  const reviewerToken = makeUserToken({
    tenant_id: "tenant_quality",
    user_id: "alice",
    groups: ["qa"],
    roles: ["reviewer"],
  });

  const memberToken = makeUserToken({
    tenant_id: "tenant_quality",
    user_id: "carol",
    groups: [],
    roles: ["member"],
  });

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    previousAnswerServiceUrl = process.env.ANSWER_SERVICE_URL;
    upstream = http.createServer((req, res) => {
      seen.push({ method: req.method, url: req.url, tenant: req.headers["x-raku-tenant-id"] });
      res.setHeader("content-type", "application/json");
      if (req.method === "GET" && req.url?.startsWith("/internal/quality/operational")) {
        res.end(
          JSON.stringify({
            query_count: 3,
            p50_ms: 12.5,
            p95_ms: 40.2,
            avg_total_tokens: 210,
            status_counts: { ok: 2, insufficient_evidence: 1 },
            insufficient_rate: 1 / 3,
            recent_refusals: [
              {
                request_id: "trace_1",
                query_redacted: "ポンプ [REDACTED:email] の点検周期",
                status: "insufficient_evidence",
                created_at: "2026-07-03T00:00:00+00:00",
              },
            ],
            low_rating_count: 1,
          }),
        );
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
    const res = await request(app.getHttpServer()).get("/v1/quality/operational");
    expect(res.status).toBe(401);
  });

  it("returns the operational summary for reviewers with tenant scope from the principal", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/quality/operational?limit=5")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", reviewerToken);

    expect(res.status).toBe(200);
    expect(res.body.query_count).toBe(3);
    expect(res.body.p95_ms).toBe(40.2);
    expect(res.body.low_rating_count).toBe(1);
    expect(res.body.recent_refusals[0].query_redacted).toContain("[REDACTED:email]");
    const last = seen[seen.length - 1];
    expect(last.method).toBe("GET");
    expect(last.url).toBe("/internal/quality/operational?limit=5");
    // Tenant scope travels as the signed principal's header, never a query param.
    expect(last.tenant).toBe("tenant_quality");
  });

  it("rejects non-reviewer roles", async () => {
    const before = seen.length;
    const res = await request(app.getHttpServer())
      .get("/v1/quality/operational")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", memberToken);

    expect(res.status).toBe(403);
    // The guard fires at the facade — nothing reaches the answer-service.
    expect(seen.length).toBe(before);
  });
});
