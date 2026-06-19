import { INestApplication } from "@nestjs/common";
import request from "supertest";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

// P0-T05 — mock auth middleware: API key + X-User-Token -> principal.
describe("auth middleware (e2e)", () => {
  let app: INestApplication;
  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    app = await createApp();
    await app.init();
  });
  afterAll(async () => app?.close());

  it("missing Bearer api key -> 401", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/whoami")
      .set("X-User-Token", makeUserToken({ tenant_id: "t", user_id: "u", groups: [], roles: [] }));
    expect(res.status).toBe(401);
  });

  it("missing X-User-Token -> 401", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/whoami")
      .set("Authorization", "Bearer local-dev-key");
    expect(res.status).toBe(401);
  });

  it("valid api key + token -> principal claims parsed", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "alice",
      groups: ["ops"],
      roles: ["reader", "admin"],
    });
    const res = await request(app.getHttpServer())
      .get("/v1/whoami")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);
    expect(res.status).toBe(200);
    expect(res.body.principal).toEqual({
      tenant_id: "tenant_a",
      user_id: "alice",
      groups: ["ops"],
      roles: ["reader", "admin"],
    });
  });
});
