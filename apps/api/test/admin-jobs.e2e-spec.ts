import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("admin ingestion status facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let previousAnswerServiceUrl: string | undefined;
  const seen: Array<{ url: string | undefined; tenant: string | string[] | undefined }> = [];

  const token = makeUserToken({
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

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    previousAnswerServiceUrl = process.env.ANSWER_SERVICE_URL;
    upstream = http.createServer((req, res) => {
      seen.push({ url: req.url, tenant: req.headers["x-raku-tenant-id"] });
      res.setHeader("content-type", "application/json");
      if (req.url?.includes("missing")) {
        res.statusCode = 404;
        res.end(JSON.stringify({ error: "not found" }));
        return;
      }
      if (req.method === "GET" && req.url === "/internal/jobs?status=failed&source_id=upload") {
        res.end(
          JSON.stringify({
            jobs: [
              {
                job_id: "ing_failed",
                ingestion_run_id: "ing_failed",
                type: "upload_ingest",
                status: "failed",
                source_id: "upload",
                retry_count: 1,
                dagster_run_id: "dagster-run-1",
                dagster_run_url: "https://dagster.example/runs/dagster-run-1",
              },
            ],
          }),
        );
        return;
      }
      if (req.method === "GET" && req.url === "/internal/ingestion-runs/ing_1") {
        res.end(
          JSON.stringify({
            ingestion_run_id: "ing_1",
            type: "upload_ingest",
            trigger: "api",
            status: "succeeded",
            collection_id: "manuals",
            source_id: "upload",
            document_id: "doc1",
            retry_count: 0,
            dagster_run_id: "dagster-run-1",
            dagster_run_url: "https://dagster.example/runs/dagster-run-1",
            summary: { observed_count: 1, changed_count: 1, deleted_count: 0, skipped_count: 0, failed_count: 0 },
            documents: [{ document_id: "doc1", parse_status: "succeeded", chunk_status: "succeeded", embedding_status: "succeeded", index_status: "succeeded" }],
          }),
        );
        return;
      }
      if (req.method === "POST" && req.url === "/internal/ingestion-runs/ing_1/retry") {
        res.end(
          JSON.stringify({
            ingestion_run_id: "ing_retry",
            document_id: "doc1",
            status: "succeeded",
            status_url: "/v1/admin/ingestion-runs/ing_retry",
            chunk_count: 2,
          }),
        );
        return;
      }
      if (req.method === "POST" && req.url === "/internal/sources/upload/sync") {
        res.end(
          JSON.stringify({
            source_id: "upload",
            collection_id: "manuals",
            status: "succeeded",
            ingestion_run_id: "ing_sync",
            status_url: "/v1/admin/ingestion-runs/ing_sync",
            observed_count: 1,
            changed_count: 1,
            failed_count: 0,
            runs: [],
          }),
        );
        return;
      }
      if (req.method === "POST" && req.url === "/internal/sources/upload/preview") {
        res.end(
          JSON.stringify({
            source_id: "upload",
            document_count: 1,
            documents: [
              {
                document_id: "sample",
                document_ref: "s3://pilot/trouble.csv",
                content_type: "text/csv",
                kind: "table",
                sample_row_count: 1,
              },
            ],
            canonical_fields: ["equipment_id", "alarm_code"],
            detected_columns: ["設備番号", "アラーム"],
            explicit_mapping: {},
            suggested_mapping: { "設備番号": "equipment_id", "アラーム": "alarm_code" },
            mapping_confidence: { "設備番号": 0.92, "アラーム": 0.92 },
            defaults: {},
            required_fields: ["equipment_id"],
            sample_rows: [
              {
                document_id: "sample",
                sheet_name: "sheet1",
                row_number: 2,
                raw: { "設備番号": "M-100", "アラーム": "E152" },
                normalized: { equipment_id: "M-100", alarm_code: "E152" },
                validation: { status: "valid", errors: [], warnings: [] },
              },
            ],
            validation: {
              valid_count: 1,
              needs_review_count: 0,
              error_count: 0,
              warning_count: 0,
              errors: [],
              warnings: [],
            },
          }),
        );
        return;
      }
      if (req.method === "POST" && req.url === "/internal/admin/collections/manuals/reindex") {
        res.end(
          JSON.stringify({
            reindex_plan_id: "rp_1",
            collection_id: "manuals",
            source_id: "upload",
            status: "planned",
            status_url: "/v1/admin/reindex-plans/rp_1",
            affected_document_count: 2,
          }),
        );
        return;
      }
      if (req.method === "GET" && req.url === "/internal/documents/doc1/processing-status") {
        res.end(
          JSON.stringify({
            document_id: "doc1",
            ingestion_run_id: "ing_1",
            parse_status: "succeeded",
            chunk_status: "succeeded",
            embedding_status: "succeeded",
            index_status: "succeeded",
          }),
        );
        return;
      }
      if (req.method === "DELETE" && req.url === "/internal/documents/doc1") {
        res.end(
          JSON.stringify({
            job_id: "delete_doc1",
            document_id: "doc1",
            status: "succeeded",
            tombstoned_chunks: 2,
            invalidated_cache_entries: 1,
            purged_chunks: 2,
          }),
        );
        return;
      }
      if (req.method === "GET" && req.url === "/internal/sources/upload/sync-status") {
        res.end(
          JSON.stringify({
            source_id: "upload",
            collection_id: "manuals",
            status: "idle",
            last_ingestion_run_id: "ing_1",
            observed_count: 1,
            changed_count: 1,
            deleted_count: 0,
            skipped_count: 0,
            failed_count: 0,
          }),
        );
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
    if (previousAnswerServiceUrl === undefined) {
      delete process.env.ANSWER_SERVICE_URL;
    } else {
      process.env.ANSWER_SERVICE_URL = previousAnswerServiceUrl;
    }
  });

  it("requires auth for admin status routes", async () => {
    const res = await request(app.getHttpServer()).get("/v1/admin/ingestion-runs/ing_1");
    expect(res.status).toBe(401);
  });

  it("GET /v1/admin/ingestion-runs/:id forwards tenant context and returns run status", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/admin/ingestion-runs/ing_1")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body.ingestion_run_id).toBe("ing_1");
    expect(res.body.summary.changed_count).toBe(1);
    expect(res.body.dagster_run_url).toBe("https://dagster.example/runs/dagster-run-1");
    expect(seen[seen.length - 1].tenant).toBe("tenant_admin");
  });

  it("GET /v1/admin/jobs forwards filters and returns job summaries", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/admin/jobs?status=failed&source_id=upload")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body.jobs[0].job_id).toBe("ing_failed");
    expect(res.body.jobs[0].status).toBe("failed");
    expect(res.body.jobs[0].dagster_run_url).toContain("/runs/dagster-run-1");
    expect(seen[seen.length - 1].url).toBe("/internal/jobs?status=failed&source_id=upload");
  });

  it("GET /v1/admin/documents/:id/processing-status returns document status", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/admin/documents/doc1/processing-status")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body.document_id).toBe("doc1");
    expect(res.body.index_status).toBe("succeeded");
  });

  it("rejects non-admin reads of processing-status (0085 defense-in-depth)", async () => {
    const before = seen.length;
    const res = await request(app.getHttpServer())
      .get("/v1/admin/documents/doc1/processing-status")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", readerToken);

    expect(res.status).toBe(403);
    // The role check runs at the facade — the request must never reach the core.
    expect(seen.length).toBe(before);
  });

  it("rejects non-admin roles before forwarding job mutations", async () => {
    const before = seen.length;

    const retry = await request(app.getHttpServer())
      .post("/v1/admin/ingestion-runs/ing_1/retry")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", readerToken);
    expect(retry.status).toBe(403);

    const reindex = await request(app.getHttpServer())
      .post("/v1/admin/collections/manuals/reindex")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", readerToken)
      .send({ source_id: "upload", reason: "reader must not reindex" });
    expect(reindex.status).toBe(403);

    const deletion = await request(app.getHttpServer())
      .delete("/v1/admin/documents/doc1")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", readerToken);
    expect(deletion.status).toBe(403);

    expect(seen.length).toBe(before);
  });

  it("POST /v1/admin/ingestion-runs/:id/retry forwards retry requests", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/admin/ingestion-runs/ing_1/retry")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(202);
    expect(res.body.ingestion_run_id).toBe("ing_retry");
    expect(seen[seen.length - 1].tenant).toBe("tenant_admin");
  });

  it("POST /v1/admin/sources/:id/sync forwards datasource sync requests", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/admin/sources/upload/sync")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ collection_id: "manuals" });

    expect(res.status).toBe(202);
    expect(res.body.ingestion_run_id).toBe("ing_sync");
    expect(seen[seen.length - 1].url).toBe("/internal/sources/upload/sync");
  });

  it("POST /v1/admin/sources/:id/preview forwards onboarding preview requests", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/admin/sources/upload/preview")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ sample_rows: 1 });

    expect(res.status).toBe(200);
    expect(res.body.suggested_mapping["設備番号"]).toBe("equipment_id");
    expect(res.body.sample_rows[0].normalized.alarm_code).toBe("E152");
    expect(seen[seen.length - 1].url).toBe("/internal/sources/upload/preview");
    expect(seen[seen.length - 1].tenant).toBe("tenant_admin");
  });

  it("POST /v1/admin/collections/:id/reindex creates a reindex plan", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/admin/collections/manuals/reindex")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ source_id: "upload", document_ids: ["doc1", "doc2"], reason: "manual" });

    expect(res.status).toBe(202);
    expect(res.body.reindex_plan_id).toBe("rp_1");
    expect(res.body.affected_document_count).toBe(2);
    expect(seen[seen.length - 1].url).toBe("/internal/admin/collections/manuals/reindex");
  });

  it("DELETE /v1/admin/documents/:id returns deletion cascade status", async () => {
    const res = await request(app.getHttpServer())
      .delete("/v1/admin/documents/doc1")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(202);
    expect(res.body.document_id).toBe("doc1");
    expect(res.body.purged_chunks).toBe(2);
  });

  it("GET /v1/admin/sources/:id/sync-status returns source status", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/admin/sources/upload/sync-status")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body.source_id).toBe("upload");
    expect(res.body.last_ingestion_run_id).toBe("ing_1");
  });

  it("preserves not-found without leaking upstream details", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/admin/ingestion-runs/missing")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(404);
  });
});
