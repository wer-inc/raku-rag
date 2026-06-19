import { INestApplication } from "@nestjs/common";
import request from "supertest";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

// P0-T05 — NestJS skeleton boot + /v1 versioning.
describe("api skeleton (e2e)", () => {
  let app: INestApplication;

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    app = await createApp();
    await app.init();
  });
  afterAll(async () => app?.close());

  it("GET /v1/health -> 200 ok (public)", async () => {
    const res = await request(app.getHttpServer()).get("/v1/health");
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("ok");
  });

  it("non-/v1 route is 404 (versioning enforced)", async () => {
    const res = await request(app.getHttpServer()).get("/health");
    expect(res.status).toBe(404);
  });

  it("protected route without auth -> 401", async () => {
    const res = await request(app.getHttpServer()).get("/v1/whoami");
    expect(res.status).toBe(401);
  });

  it("protected route with Bearer + X-User-Token -> 200 + principal", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_local",
      user_id: "u1",
      groups: ["g1"],
      roles: ["reader"],
    });
    const res = await request(app.getHttpServer())
      .get("/v1/whoami")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);
    expect(res.status).toBe(200);
    expect(res.body.principal.tenant_id).toBe("tenant_local");
    expect(res.body.principal.roles).toContain("reader");
  });
});
