import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("assets facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let previousAnswerServiceUrl: string | undefined;
  let seenUrl = "";
  let seenTenant: string | string[] | undefined;

  const token = makeUserToken({
    tenant_id: "tenant_a",
    user_id: "alice",
    groups: ["ops"],
    roles: ["reader"],
  });

  const CANNED = {
    asset_id: "asset_1",
    tenant_id: "tenant_a",
    collection_id: "manuals",
    document_id: "panel_image",
    source_id: "visual",
    version: 1,
    storage_uri: "s3://bucket/asset_1.png",
    content_type: "image/png",
    page_number: 1,
    regions: [
      {
        region_id: "asset_1:region:1",
        chunk_id: "panel_image:visual:0",
        region_type: "text",
        page_number: 1,
        bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
        crop_uri: "memory://crops/tenant_a/crop:asset_1:region:1",
      },
    ],
    crops: [
      {
        crop_id: "crop:asset_1:asset_1:region:1",
        asset_id: "asset_1",
        region_id: "asset_1:region:1",
        crop_uri: "memory://crops/tenant_a/crop:asset_1:region:1",
        bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
        redaction_policy_ref: "inherit",
      },
    ],
  };

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    previousAnswerServiceUrl = process.env.ANSWER_SERVICE_URL;
    upstream = http.createServer((req, res) => {
      seenUrl = req.url ?? "";
      seenTenant = req.headers["x-raku-tenant-id"];
      res.setHeader("content-type", "application/json");
      if (req.method === "GET" && req.url === "/internal/assets/asset_1") {
        res.end(JSON.stringify(CANNED));
        return;
      }
      if (req.method === "GET" && req.url === "/internal/assets/missing") {
        res.statusCode = 404;
        res.end(JSON.stringify({ error: "not found" }));
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
    process.env.ANSWER_SERVICE_URL = previousAnswerServiceUrl;
  });

  it("GET /v1/assets/:asset_id without auth -> 401", async () => {
    const res = await request(app.getHttpServer()).get("/v1/assets/asset_1");
    expect(res.status).toBe(401);
  });

  it("GET /v1/assets/:asset_id forwards signed principal and returns authorized asset regions", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/assets/asset_1")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body.asset_id).toBe("asset_1");
    expect(res.body.regions[0].bbox.width).toBe(0.3);
    expect(res.body.crops[0].redaction_policy_ref).toBe("inherit");
    expect(seenUrl).toBe("/internal/assets/asset_1");
    expect(seenTenant).toBe("tenant_a");
  });

  it("returns 404 for missing, unauthorized, or deleted assets", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/assets/missing")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(404);
  });

  it("502 when the answer-service is unreachable", async () => {
    const saved = process.env.ANSWER_SERVICE_URL;
    process.env.ANSWER_SERVICE_URL = "http://127.0.0.1:1";
    try {
      const res = await request(app.getHttpServer())
        .get("/v1/assets/asset_1")
        .set("Authorization", "Bearer local-dev-key")
        .set("X-User-Token", token);
      expect(res.status).toBe(502);
    } finally {
      process.env.ANSWER_SERVICE_URL = saved;
    }
  });
});
