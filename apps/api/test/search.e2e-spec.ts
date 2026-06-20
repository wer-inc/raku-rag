import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("search facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let received: Record<string, unknown> | null = null;
  let receivedMethod = "";
  let receivedPath = "";

  const CANNED = {
    results: [
      {
        source_id: "src",
        document_id: "d1",
        chunk_id: "d1:0",
        version: 1,
        retrieval_score: 0.91,
        heading_path: ["Manual"],
        text: "maintenance interval is ninety days",
        freshness: { indexed_at: "2026-06-20T00:00:00Z", document_version: 1, source_freshness: null },
      },
    ],
    correlation_id: "trace_search_stub",
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
        if (receivedMethod !== "POST" || receivedPath !== "/internal/search") {
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

  it("POST /v1/search without auth -> 401", async () => {
    const res = await request(app.getHttpServer()).post("/v1/search").send({ query: "x" });
    expect(res.status).toBe(401);
  });

  it("POST /v1/search forwards query and signed principal to the answer-service", async () => {
    const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: ["ops"], roles: ["reader"] });
    const res = await request(app.getHttpServer())
      .post("/v1/search")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ query: "maintenance interval", collection_id: "manuals", top_k: 3 });

    expect(res.status).toBe(200);
    expect(res.body.results[0].document_id).toBe("d1");
    expect(res.body.correlation_id).toBe("trace_search_stub");
    expect(received?.query).toBe("maintenance interval");
    expect(received?.tenant_id).toBe("tenant_a");
    expect(received?.collection_id).toBe("manuals");
    expect(received?.top_k).toBe(3);
    expect(receivedMethod).toBe("POST");
    expect(receivedPath).toBe("/internal/search");
  });

  it("SECURITY: tenant comes from the signed token, never from the request body", async () => {
    const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: [], roles: [] });
    const res = await request(app.getHttpServer())
      .post("/v1/search")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ query: "x", tenant_id: "tenant_victim" });

    expect(res.status).toBe(200);
    expect(received?.tenant_id).toBe("tenant_a");
  });

  it("502 when the answer-service is unreachable", async () => {
    const saved = process.env.ANSWER_SERVICE_URL;
    process.env.ANSWER_SERVICE_URL = "http://127.0.0.1:1";
    try {
      const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: [], roles: [] });
      const res = await request(app.getHttpServer())
        .post("/v1/search")
        .set("Authorization", "Bearer local-dev-key")
        .set("X-User-Token", token)
        .send({ query: "x" });
      expect(res.status).toBe(502);
    } finally {
      process.env.ANSWER_SERVICE_URL = saved;
    }
  });
});
