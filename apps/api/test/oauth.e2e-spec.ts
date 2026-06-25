import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("google oauth relay (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let previousAnswerServiceUrl: string | undefined;
  let previousClientId: string | undefined;
  const seen: Array<{ method?: string; url?: string; tenant?: string | string[]; body: any }> = [];

  const adminToken = makeUserToken({
    tenant_id: "tenant_admin",
    user_id: "ops",
    groups: ["platform"],
    roles: ["admin"],
  });
  const readerToken = makeUserToken({
    tenant_id: "tenant_admin",
    user_id: "reader",
    groups: ["platform"],
    roles: ["reader"],
  });

  function send(res: http.ServerResponse, status: number, payload: unknown) {
    res.statusCode = status;
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify(payload));
  }

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    previousClientId = process.env.GOOGLE_OAUTH_CLIENT_ID;
    process.env.GOOGLE_OAUTH_CLIENT_ID = "client-xyz.apps.googleusercontent.com";
    previousAnswerServiceUrl = process.env.ANSWER_SERVICE_URL;
    upstream = http.createServer((req, res) => {
      const chunks: Buffer[] = [];
      req.on("data", (c) => chunks.push(Buffer.from(c)));
      req.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        const body = raw ? JSON.parse(raw) : undefined;
        seen.push({ method: req.method, url: req.url, tenant: req.headers["x-raku-tenant-id"], body });
        if (req.method === "POST" && req.url === "/internal/oauth/google/callback") {
          send(res, 200, { connection_id: "conn-abc", refresh_token_stored: true });
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
    if (previousAnswerServiceUrl === undefined) delete process.env.ANSWER_SERVICE_URL;
    else process.env.ANSWER_SERVICE_URL = previousAnswerServiceUrl;
    if (previousClientId === undefined) delete process.env.GOOGLE_OAUTH_CLIENT_ID;
    else process.env.GOOGLE_OAUTH_CLIENT_ID = previousClientId;
  });

  it("requires auth", async () => {
    const res = await request(app.getHttpServer()).get("/v1/oauth/google/authorize?state=n1");
    expect(res.status).toBe(401);
  });

  it("builds a Google consent URL with offline access + state", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/oauth/google/authorize?state=nonce-123")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken);
    expect(res.status).toBe(200);
    const url = new URL(res.body.authorization_url);
    expect(url.origin + url.pathname).toBe("https://accounts.google.com/o/oauth2/v2/auth");
    expect(url.searchParams.get("client_id")).toBe("client-xyz.apps.googleusercontent.com");
    expect(url.searchParams.get("access_type")).toBe("offline");
    expect(url.searchParams.get("prompt")).toBe("consent");
    expect(url.searchParams.get("scope")).toContain("drive.readonly");
    expect(url.searchParams.get("state")).toBe("nonce-123");
  });

  it("rejects authorize without state", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/oauth/google/authorize")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken);
    expect(res.status).toBe(400);
  });

  it("relays the callback to the answer-service with tenant context", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/oauth/google/callback")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken)
      .send({ code: "auth-code", state: "nonce-123", redirect_uri: "https://app/cb" });
    expect(res.status).toBe(200);
    expect(res.body.connection_id).toBe("conn-abc");
    expect(res.body.refresh_token_stored).toBe(true);
    const last = seen[seen.length - 1];
    expect(last.url).toBe("/internal/oauth/google/callback");
    expect(last.tenant).toBe("tenant_admin");
    expect(last.body.code).toBe("auth-code");
    expect(last.body.provider).toBe("google_drive");
    // the API does NOT exchange the code itself; it never receives client_secret
    expect(last.body.client_secret).toBeUndefined();
  });

  it("rejects non-admin roles on the callback", async () => {
    const before = seen.length;
    const res = await request(app.getHttpServer())
      .post("/v1/oauth/google/callback")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", readerToken)
      .send({ code: "auth-code", state: "n", redirect_uri: "https://app/cb" });
    expect(res.status).toBe(403);
    expect(seen.length).toBe(before); // never forwarded
  });

  it("rejects callback without code", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/oauth/google/callback")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", adminToken)
      .send({ state: "n" });
    expect(res.status).toBe(400);
  });
});
