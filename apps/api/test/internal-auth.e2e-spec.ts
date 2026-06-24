import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

// B6: the answer-service enforces the internal-boundary shared secret; the API must forward it as
// X-Internal-Auth on every /internal/* call or the gate 401s (502 at the facade). These assert the
// header is forwarded when RAKU_INTERNAL_AUTH_SECRET is set (GET via principalHeaders, POST via the
// inline header path) and omitted when it is unset (no-op gate, no behaviour change).
describe("internal-auth forwarding (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let prevUrl: string | undefined;
  let prevSecret: string | undefined;
  let seenInternalAuth: string | string[] | undefined;

  const SECRET = "test-internal-secret";
  const token = makeUserToken({
    tenant_id: "tenant_a",
    user_id: "alice",
    groups: ["manuals"],
    roles: ["tenant_admin"],
  });

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    prevUrl = process.env.ANSWER_SERVICE_URL;
    prevSecret = process.env.RAKU_INTERNAL_AUTH_SECRET;
    process.env.RAKU_INTERNAL_AUTH_SECRET = SECRET;
    upstream = http.createServer((req, res) => {
      seenInternalAuth = req.headers["x-internal-auth"];
      res.setHeader("content-type", "application/json");
      if (req.url === "/internal/manufacturing/documents") {
        res.end(JSON.stringify({ documents: [] }));
        return;
      }
      if (req.url === "/internal/manufacturing/answer") {
        res.end(JSON.stringify({ status: "ok", citations: [] }));
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
    process.env.ANSWER_SERVICE_URL = prevUrl;
    if (prevSecret === undefined) {
      delete process.env.RAKU_INTERNAL_AUTH_SECRET;
    } else {
      process.env.RAKU_INTERNAL_AUTH_SECRET = prevSecret;
    }
  });

  beforeEach(() => {
    seenInternalAuth = undefined;
    process.env.RAKU_INTERNAL_AUTH_SECRET = SECRET;
  });

  it("forwards X-Internal-Auth on a GET (principalHeaders path)", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/manufacturing/documents")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);
    expect(res.status).toBe(200);
    expect(seenInternalAuth).toBe(SECRET);
  });

  it("forwards X-Internal-Auth on a POST (inline header path)", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/manufacturing/answer")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ query: "torque" });
    expect(res.status).toBe(200);
    expect(seenInternalAuth).toBe(SECRET);
  });

  it("omits X-Internal-Auth when the secret is unset (no-op gate)", async () => {
    delete process.env.RAKU_INTERNAL_AUTH_SECRET;
    const res = await request(app.getHttpServer())
      .get("/v1/manufacturing/documents")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);
    expect(res.status).toBe(200);
    expect(seenInternalAuth).toBeUndefined();
  });
});
