import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

describe("admin settings facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let previousAnswerServiceUrl: string | undefined;
  const seen: Array<{
    method: string | undefined;
    url: string | undefined;
    tenant: string | string[] | undefined;
    body: any;
  }> = [];

  const token = makeUserToken({
    tenant_id: "tenant_admin",
    user_id: "ops",
    groups: ["platform"],
    roles: ["admin"],
  });

  function send(res: http.ServerResponse, status: number, payload: unknown) {
    const data = JSON.stringify(payload);
    res.statusCode = status;
    res.setHeader("content-type", "application/json");
    res.end(data);
  }

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    previousAnswerServiceUrl = process.env.ANSWER_SERVICE_URL;
    upstream = http.createServer((req, res) => {
      const chunks: Buffer[] = [];
      req.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
      req.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        const body = raw ? JSON.parse(raw) : undefined;
        seen.push({ method: req.method, url: req.url, tenant: req.headers["x-raku-tenant-id"], body });

        if (req.method === "GET" && req.url === "/internal/admin/provider-policies?collection_id=manuals") {
          send(res, 200, [
            {
              provider_policy_id: "default",
              tenant_id: "tenant_admin",
              name: "Default provider policy",
              status: "active",
              parser_mode: "aws_only",
              zero_retention_required: true,
              no_train_required: true,
              customer_opt_in_required: true,
            },
          ]);
          return;
        }
        if (req.method === "PUT" && req.url === "/internal/admin/datasources/upload-main") {
          send(res, 200, {
            source_id: "upload-main",
            tenant_id: "tenant_admin",
            collection_id: body.collection_id,
            type: body.type,
            config: body.config,
            status: "active",
            provider_config_audit_event_id: "aud_ds",
          });
          return;
        }
        if (req.method === "GET" && req.url === "/internal/admin/datasources/upload-main") {
          send(res, 200, {
            source_id: "upload-main",
            tenant_id: "tenant_admin",
            collection_id: "manuals",
            type: "object_storage",
            config: { bucket: "manuals" },
            status: "active",
          });
          return;
        }
        if (req.method === "PUT" && req.url === "/internal/admin/query-profiles/default") {
          send(res, 200, {
            profile_id: "default",
            tenant_id: "tenant_admin",
            score_threshold: body.score_threshold,
            top_k: body.top_k,
            minimum_evidence_count: 2,
            rerank_enabled: true,
            rerank_top_n: 20,
            max_context_tokens: body.max_context_tokens ?? 8000,
            max_context_chunks: body.max_context_chunks ?? 8,
            max_synchronous_llm_calls: body.max_synchronous_llm_calls ?? 1,
            captioning_enabled: body.captioning_enabled,
            profile_version: 1,
            schema_version: 1,
            effective_from: null,
            deprecated_at: null,
            provider_config_audit_event_id: "aud_query",
          });
          return;
        }
        if (req.method === "PUT" && req.url === "/internal/admin/provider-policies/default") {
          send(res, 200, {
            provider_policy_id: "default",
            tenant_id: "tenant_admin",
            name: "Default provider policy",
            status: "active",
            parser_mode: body.parser_mode,
            zero_retention_required: true,
            no_train_required: true,
            customer_opt_in_required: true,
            customer_opt_in_status: body.customer_opt_in_status,
            provider_config_audit_event_id: "aud_provider",
          });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/admin/provider-policies/default/validate") {
          send(res, 200, {
            allowed: false,
            reasons: ["customer opt-in is required before this provider can process content"],
            required_opt_in: true,
            effective_provider: body.provider,
          });
          return;
        }
        if (req.method === "PUT" && req.url === "/internal/admin/retrieval-profiles/default") {
          send(res, 200, {
            retrieval_profile_id: "default",
            tenant_id: "tenant_admin",
            name: "Default retrieval profile",
            version: 2,
            status: "active",
            metadata_filter_required: body.metadata_filter_required,
            identifier_match_enabled: true,
            identifier_fields: body.identifier_fields,
            vector_search_enabled: true,
            vector_top_k: body.vector_top_k,
            rerank_enabled: body.rerank_enabled,
            rerank_candidate_limit: 50,
            final_context_limit: 5,
            max_context_tokens: body.max_context_tokens ?? 8000,
            minimum_evidence_count: 2,
            fallback_behavior: "insufficient_evidence",
            profile_version: 1,
            schema_version: 1,
            effective_from: null,
            deprecated_at: null,
            provider_config_audit_event_id: "aud_retrieval",
          });
          return;
        }
        if (req.method === "POST" && req.url === "/internal/admin/retrieval-profiles/default/benchmark") {
          send(res, 202, {
            evaluation_run_id: "eval_retrieval",
            status_url: "/v1/evaluations/runs/eval_retrieval",
          });
          return;
        }
        if (req.method === "PUT" && req.url === "/internal/admin/logging-policies/default") {
          send(res, 200, {
            logging_policy_id: "default",
            tenant_id: "tenant_admin",
            name: "Default logging policy",
            status: "active",
            raw_user_query_storage: body.raw_user_query_storage,
            raw_retrieved_context_storage: body.raw_retrieved_context_storage,
            model_input_storage: "disabled",
            model_output_storage: "disabled",
            store_citation_ids: true,
            store_chunk_ids: true,
            store_prompt_template_version: true,
            store_model_metadata: true,
            store_latency: true,
            store_cost: true,
            production_sampling_rate: body.production_sampling_rate,
            profile_version: 1,
            schema_version: 1,
            effective_from: null,
            deprecated_at: null,
            provider_config_audit_event_id: "aud_logging",
          });
          return;
        }
        if (
          req.method === "GET" &&
          req.url === "/internal/admin/provider-config-audit-events?event_type=parser_provider_changed"
        ) {
          send(res, 200, [
            {
              provider_config_audit_event_id: "aud_parser",
              tenant_id: "tenant_admin",
              collection_id: "manuals",
              event_type: "parser_provider_changed",
              actor: "ops",
              redacted_before: { parser_mode: "aws_only" },
              redacted_after: { parser_mode: "azure_document_intelligence_allowed" },
              reason: "enable external parser",
              created_at: "2026-06-20T00:00:00Z",
              correlation_id: "default",
            },
          ]);
          return;
        }
        if (req.method === "PUT" && req.url === "/internal/admin/acl") {
          send(res, 200, {
            grants: [
              {
                grant_id: "grant_1",
                tenant_id: "tenant_admin",
                scope_type: "collection",
                scope_id: "manuals",
                subject_type: "group",
                subject_id: "platform",
                permission: "read",
              },
            ],
            provider_config_audit_event_id: "aud_acl",
          });
          return;
        }
        if (req.method === "PUT" && req.url === "/internal/admin/budgets") {
          send(res, 200, {
            budgets: [
              {
                budget_id: "tenant:tenant_admin",
                tenant_id: "tenant_admin",
                scope_type: "tenant",
                scope_id: "tenant_admin",
                limit: body.budgets[0].limit,
                spent: 0,
                currency: "USD",
                period: "monthly",
                status: "active",
              },
            ],
            provider_config_audit_event_id: "aud_budget",
          });
          return;
        }
        send(res, 500, { error: `wrong upstream route ${req.method} ${req.url}` });
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

  it("requires auth for admin settings routes", async () => {
    const res = await request(app.getHttpServer()).get("/v1/admin/provider-policies");
    expect(res.status).toBe(401);
  });

  it("lists provider policies with tenant context and filters", async () => {
    const res = await request(app.getHttpServer())
      .get("/v1/admin/provider-policies?collection_id=manuals")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body[0].provider_policy_id).toBe("default");
    expect(seen[seen.length - 1].url).toBe("/internal/admin/provider-policies?collection_id=manuals");
    expect(seen[seen.length - 1].tenant).toBe("tenant_admin");
  });

  it("upserts data sources and query profiles without accepting body tenant overrides", async () => {
    const dataSource = await request(app.getHttpServer())
      .put("/v1/admin/datasources/upload-main")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        tenant_id: "evil",
        collection_id: "manuals",
        type: "object_storage",
        config: { bucket: "manuals" },
      });

    expect(dataSource.status).toBe(200);
    expect(dataSource.body.tenant_id).toBe("tenant_admin");
    expect(seen[seen.length - 1].body.tenant_id).toBeUndefined();

    const fetched = await request(app.getHttpServer())
      .get("/v1/admin/datasources/upload-main")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);
    expect(fetched.status).toBe(200);
    expect(fetched.body.config.bucket).toBe("manuals");

    const queryProfile = await request(app.getHttpServer())
      .put("/v1/admin/query-profiles/default")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ tenant_id: "evil", score_threshold: 0.42, top_k: 8, captioning_enabled: true });

    expect(queryProfile.status).toBe(200);
    expect(queryProfile.body.captioning_enabled).toBe(true);
    expect(seen[seen.length - 1].body.tenant_id).toBeUndefined();
  });

  it("updates provider, retrieval, and logging policies", async () => {
    const provider = await request(app.getHttpServer())
      .put("/v1/admin/provider-policies/default")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        parser_mode: "azure_document_intelligence_allowed",
        customer_opt_in_status: "pending",
        reason: "trial request",
      });
    expect(provider.status).toBe(200);
    expect(provider.body.provider_config_audit_event_id).toBe("aud_provider");

    const validation = await request(app.getHttpServer())
      .post("/v1/admin/provider-policies/default/validate")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ operation: "parse", provider: "azure_document_intelligence" });
    expect(validation.status).toBe(200);
    expect(validation.body.allowed).toBe(false);

    const retrieval = await request(app.getHttpServer())
      .put("/v1/admin/retrieval-profiles/default")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        metadata_filter_required: true,
        identifier_fields: ["model_number"],
        vector_top_k: 20,
        rerank_enabled: true,
        max_context_tokens: 8000,
      });
    expect(retrieval.status).toBe(200);
    expect(retrieval.body.identifier_fields).toContain("model_number");

    const benchmark = await request(app.getHttpServer())
      .post("/v1/admin/retrieval-profiles/default/benchmark")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ sample_size: 20 });
    expect(benchmark.status).toBe(202);
    expect(benchmark.body.evaluation_run_id).toBe("eval_retrieval");

    const logging = await request(app.getHttpServer())
      .put("/v1/admin/logging-policies/default")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        raw_user_query_storage: "disabled",
        raw_retrieved_context_storage: "disabled",
        production_sampling_rate: 0.25,
      });
    expect(logging.status).toBe(200);
    expect(logging.body.raw_retrieved_context_storage).toBe("disabled");
  });

  it("lists provider config audit events with redacted before and after snapshots", async () => {
    const events = await request(app.getHttpServer())
      .get("/v1/admin/provider-config-audit-events?event_type=parser_provider_changed")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(events.status).toBe(200);
    expect(events.body[0].event_type).toBe("parser_provider_changed");
    expect(events.body[0].redacted_before.parser_mode).toBe("aws_only");
    expect(events.body[0].redacted_after.parser_mode).toBe("azure_document_intelligence_allowed");
    expect(seen[seen.length - 1].url).toBe(
      "/internal/admin/provider-config-audit-events?event_type=parser_provider_changed",
    );
  });

  it("updates ACL and budget settings while stripping nested tenant overrides", async () => {
    const acl = await request(app.getHttpServer())
      .put("/v1/admin/acl")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        grants: [
          {
            grant_id: "grant_1",
            tenant_id: "evil",
            scope_type: "collection",
            scope_id: "manuals",
            subject_type: "group",
            subject_id: "platform",
            permission: "read",
          },
        ],
      });
    expect(acl.status).toBe(200);
    expect(acl.body.grants[0].tenant_id).toBe("tenant_admin");
    expect(seen[seen.length - 1].body.grants[0].tenant_id).toBeUndefined();

    const budget = await request(app.getHttpServer())
      .put("/v1/admin/budgets")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        budgets: [
          {
            budget_id: "tenant:tenant_admin",
            tenant_id: "evil",
            scope_type: "tenant",
            scope_id: "tenant_admin",
            limit: 100,
          },
        ],
      });
    expect(budget.status).toBe(200);
    expect(budget.body.budgets[0].limit).toBe(100);
    expect(seen[seen.length - 1].body.budgets[0].tenant_id).toBeUndefined();
  });
});
