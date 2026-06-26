import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createSign, generateKeyPairSync } from "crypto";
import { createApp } from "../src/main";
import { clearCognitoJwksCache } from "../src/auth/cognito";
import { makeUserToken } from "../src/auth/principal";

function b64Json(value: unknown): string {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

describe("Cognito auth mode (e2e)", () => {
  let app: INestApplication;
  let jwks: http.Server;
  let jwksUri = "";
  const previousEnv: Record<string, string | undefined> = {};
  const issuer = "https://cognito-idp.ap-northeast-1.amazonaws.com/apne1_pool";
  const clientId = "client-123";
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const jwk = { ...(publicKey.export({ format: "jwk" }) as JsonWebKey), kid: "kid-1", alg: "RS256", use: "sig" };

  function token(overrides: Record<string, unknown> = {}) {
    const header = b64Json({ alg: "RS256", kid: "kid-1", typ: "JWT" });
    const payload = b64Json({
      iss: issuer,
      aud: clientId,
      exp: Math.floor(Date.now() / 1000) + 300,
      token_use: "id",
      sub: "sub-1",
      email: "alice@example.com",
      "custom:tenant_id": "tenant_prod",
      "cognito:groups": ["tenant_admin", "reviewer"],
      ...overrides,
    });
    const sig = createSign("RSA-SHA256").update(`${header}.${payload}`).sign(privateKey, "base64url");
    return `${header}.${payload}.${sig}`;
  }

  beforeAll(async () => {
    for (const key of ["RAKU_AUTH_MODE", "COGNITO_ISSUER", "COGNITO_CLIENT_ID", "COGNITO_JWKS_URI", "NODE_ENV"]) {
      previousEnv[key] = process.env[key];
    }
    process.env.NODE_ENV = "test";
    jwks = http.createServer((_req, res) => {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ keys: [jwk] }));
    });
    await new Promise<void>((resolve) => jwks.listen(0, "127.0.0.1", resolve));
    jwksUri = `http://127.0.0.1:${(jwks.address() as AddressInfo).port}/.well-known/jwks.json`;
    process.env.RAKU_AUTH_MODE = "cognito";
    process.env.COGNITO_ISSUER = issuer;
    process.env.COGNITO_CLIENT_ID = clientId;
    process.env.COGNITO_JWKS_URI = jwksUri;
    clearCognitoJwksCache();
    app = await createApp();
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    await new Promise<void>((resolve) => jwks.close(() => resolve()));
    clearCognitoJwksCache();
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  });

  it("accepts a Cognito JWT and derives principal from signed claims", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/whoami")
      .set("Authorization", `Bearer ${token()}`);
    expect(res.status).toBe(200);
    expect(res.body.principal).toEqual({
      tenant_id: "tenant_prod",
      user_id: "alice@example.com",
      groups: ["tenant_admin", "reviewer"],
      roles: ["tenant_admin", "reviewer"],
    });
  });

  it("rejects dev X-User-Token in Cognito mode", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/whoami")
      .set("Authorization", `Bearer ${token()}`)
      .set("X-User-Token", makeUserToken({ tenant_id: "evil", user_id: "mallory", groups: [], roles: [] }));
    expect(res.status).toBe(401);
  });

  it("rejects wrong audience and expired tokens", async () => {
    const wrongAudience = await request(app.getHttpServer())
      .get("/v1/whoami")
      .set("Authorization", `Bearer ${token({ aud: "other-client" })}`);
    expect(wrongAudience.status).toBe(401);

    const expired = await request(app.getHttpServer())
      .get("/v1/whoami")
      .set("Authorization", `Bearer ${token({ exp: Math.floor(Date.now() / 1000) - 1 })}`);
    expect(expired.status).toBe(401);
  });
});
