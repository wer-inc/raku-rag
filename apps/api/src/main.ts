import "reflect-metadata";
import { NestFactory } from "@nestjs/core";
import { VersioningType } from "@nestjs/common";
import { AppModule } from "./app.module";

// P0-T06 — NestJS skeleton boot with URI /v1 versioning. Routes are served under /v1/*.
export async function createApp() {
  const app = await NestFactory.create(AppModule, { logger: ["error", "warn", "log"] });
  app.enableVersioning({ type: VersioningType.URI, defaultVersion: "1" });
  return app;
}

async function bootstrap() {
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
