import { INestApplication } from "@nestjs/common";
import request from "supertest";
import { createApp } from "../src/main";

describe("api versioning headers (e2e)", () => {
  const saved = {
    deprecated: process.env.RAKU_API_V1_DEPRECATED,
    deprecation: process.env.RAKU_API_V1_DEPRECATION,
    sunset: process.env.RAKU_API_V1_SUNSET,
    url: process.env.RAKU_API_V1_DEPRECATION_URL,
  };

  afterEach(() => {
    if (saved.deprecated === undefined) {
      delete process.env.RAKU_API_V1_DEPRECATED;
    } else {
      process.env.RAKU_API_V1_DEPRECATED = saved.deprecated;
    }
    if (saved.deprecation === undefined) {
      delete process.env.RAKU_API_V1_DEPRECATION;
    } else {
      process.env.RAKU_API_V1_DEPRECATION = saved.deprecation;
    }
    if (saved.sunset === undefined) {
      delete process.env.RAKU_API_V1_SUNSET;
    } else {
      process.env.RAKU_API_V1_SUNSET = saved.sunset;
    }
    if (saved.url === undefined) {
      delete process.env.RAKU_API_V1_DEPRECATION_URL;
    } else {
      process.env.RAKU_API_V1_DEPRECATION_URL = saved.url;
    }
  });

  it("sets api-version on current /v1 responses", async () => {
    process.env.NODE_ENV = "test";
    const app: INestApplication = await createApp();
    await app.init();
    try {
      const res = await request(app.getHttpServer()).get("/v1/health");
      expect(res.status).toBe(200);
      expect(res.headers["api-version"]).toBe("1");
      expect(res.headers.deprecation).toBeUndefined();
      expect(res.headers.sunset).toBeUndefined();
    } finally {
      await app.close();
    }
  });

  it("sets Deprecation/Sunset/Link when v1 is configured as deprecated", async () => {
    process.env.NODE_ENV = "test";
    process.env.RAKU_API_V1_DEPRECATED = "1";
    process.env.RAKU_API_V1_DEPRECATION = "true";
    process.env.RAKU_API_V1_SUNSET = "Wed, 31 Dec 2026 23:59:59 GMT";
    process.env.RAKU_API_V1_DEPRECATION_URL = "https://docs.example.test/raku-rag/api-deprecations";
    const app: INestApplication = await createApp();
    await app.init();
    try {
      const res = await request(app.getHttpServer()).get("/v1/health");
      expect(res.status).toBe(200);
      expect(res.headers["api-version"]).toBe("1");
      expect(res.headers.deprecation).toBe("true");
      expect(res.headers.sunset).toBe("Wed, 31 Dec 2026 23:59:59 GMT");
      expect(res.headers.link).toBe("<https://docs.example.test/raku-rag/api-deprecations>; rel=\"deprecation\"");
    } finally {
      await app.close();
    }
  });
});
