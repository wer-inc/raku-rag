import "reflect-metadata";
import { NestFactory } from "@nestjs/core";
import { VersioningType } from "@nestjs/common";
import type { Request, Response, NextFunction } from "express";
import { AppModule } from "./app.module";
import { authMode } from "./auth/auth.middleware";
import { tokenSecret } from "./auth/principal";
import { versionHeaderPolicy } from "./versioning/version-policy";

// P0-T06 — NestJS skeleton boot with URI /v1 versioning. Routes are served under /v1/*.
export async function createApp() {
  const app = await NestFactory.create(AppModule, { logger: ["error", "warn", "log"] });
  app.use((req: Request, res: Response, next: NextFunction) => {
    const { headers } = versionHeaderPolicy(req.originalUrl ?? req.url ?? "");
    for (const [name, value] of Object.entries(headers)) {
      res.setHeader(name, value);
    }
    next();
  });
  const corsOrigins = (process.env.RAKU_CORS_ORIGIN ?? "http://localhost:3002,http://127.0.0.1:3002")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  app.enableCors({
    origin(origin: string | undefined, callback: (err: Error | null, allow?: boolean) => void) {
      if (!origin || corsOrigins.includes(origin)) {
        callback(null, true);
        return;
      }
      callback(null, false);
    },
    methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders: ["authorization", "x-user-token", "content-type"],
    exposedHeaders: ["api-version", "deprecation", "sunset", "link"],
  });
  app.enableVersioning({ type: VersioningType.URI, defaultVersion: "1" });
  return app;
}

async function bootstrap() {
  // Fail fast at boot if the token signing secret is misconfigured, rather than 500-ing on the first
  // request (or, worse, silently accepting forged tokens signed with the public default).
  if (authMode() === "dev") {
    tokenSecret();
  }
  const app = await createApp();
  const port = Number(process.env.API_PORT ?? 3000);
  await app.listen(port);
  // eslint-disable-next-line no-console
  console.log(`api listening on http://localhost:${port}/v1`);
}

// Only auto-bootstrap when run directly (tests import createApp()).
if (process.env.NODE_ENV !== "test") {
  bootstrap();
}
