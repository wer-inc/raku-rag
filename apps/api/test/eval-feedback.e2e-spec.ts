import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("evaluation and feedback facades (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let previousAnswerServiceUrl: string | undefined;
  const seen: Array<{ method: string | undefined; url: string | undefined; tenant: string | string[] | undefined; body: any }> = [];

  const token = makeUserToken({
    tenant_id: "tenant_eval",
    user_id: "alice",
    groups: ["qa"],
    roles: ["admin"],
  });

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    previousAnswerServiceUrl = process.env.ANSWER_SERVICE_URL;
    upstream = http.createServer((req, res) => {
      let data = "";
      req.on("data", (c) => (data += c));
      req.on("end", () => {
        const body = JSON.parse(data || "{}");
        seen.push({ method: req.method, url: req.url, tenant: req.headers["x-raku-tenant-id"], body });
        res.setHeader("content-type", "application/json");
        if (req.method === "POST" && req.url === "/internal/evaluations/sets") {
          res.statusCode = 201;
          res.end(JSON.stringify({
            eval_set_id: "eval_set_1",
            dataset_version: "dataset_stub",
            item_count: body.items.length,
            status: "created",
          }));
          return;
        }
        if (req.method === "POST" && req.url === "/internal/evaluations/runs") {
          res.statusCode = 202;
          res.end(JSON.stringify({ run_id: "eval_run_1", status_url: "/v1/evaluations/runs/eval_run_1" }));
          return;
        }
        if (req.method === "GET" && req.url === "/internal/evaluations/runs/eval_run_1") {
          res.end(
            JSON.stringify({
              run_id: "eval_run_1",
              eval_set_id: "eval_set_1",
              tenant_id: "tenant_eval",
              status: "succeeded",
              baseline: false,
              metrics: { recall_at_k: 1, citation_accuracy: 1 },
              baseline_comparison: {},
              security_checks: { acl_leakage: { passed: true, count: 0 } },
              gate_result: "passed",
              version_registry: {
                dataset_version: "dataset_stub",
                embedding_model_version: "hashing-bow-v1",
                prompt_template_version: "answer-grounded-contract-v1",
              },
            }),
          );
          return;
        }
        if (req.method === "POST" && req.url === "/internal/feedback") {
          res.statusCode = 202;
          res.end(JSON.stringify({ feedback_id: "fb_1", status: "accepted" }));
          return;
        }
        res.statusCode = 500;
        res.end(JSON.stringify({ error: "wrong upstream route" }));
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
    if (previousAnswerServiceUrl === undefined) {
      delete process.env.ANSWER_SERVICE_URL;
    } else {
      process.env.ANSWER_SERVICE_URL = previousAnswerServiceUrl;
    }
  });

  it("requires auth for evaluation routes", async () => {
    const res = await request(app.getHttpServer()).post("/v1/evaluations/sets").send({ items: [] });
    expect(res.status).toBe(401);
  });

  it("creates evaluation sets and forwards tenant context", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/evaluations/sets")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ items: [{ question: "when?", expected_evidence: [{ document_id: "d1" }] }] });

    expect(res.status).toBe(201);
    expect(res.body.eval_set_id).toBe("eval_set_1");
    expect(res.body.dataset_version).toBe("dataset_stub");
    expect(seen[seen.length - 1].tenant).toBe("tenant_eval");
  });

  it("starts and reads evaluation runs", async () => {
    const create = await request(app.getHttpServer())
      .post("/v1/evaluations/runs")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ eval_set_id: "eval_set_1", collection_id: "manuals", baseline: true });

    expect(create.status).toBe(202);
    expect(create.body.run_id).toBe("eval_run_1");
    expect(seen[seen.length - 1].body.baseline).toBe(true);

    const status = await request(app.getHttpServer())
      .get("/v1/evaluations/runs/eval_run_1")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(status.status).toBe(200);
    expect(status.body.gate_result).toBe("passed");
    expect(status.body.version_registry.dataset_version).toBe("dataset_stub");
  });

  it("accepts feedback", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/feedback")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ answer_id: "ans_1", subject: "user", rating: 5, comment: "useful" });

    expect(res.status).toBe(202);
    expect(res.body.feedback_id).toBe("fb_1");
    expect(seen[seen.length - 1].url).toBe("/internal/feedback");
  });
});
