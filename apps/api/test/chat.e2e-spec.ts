import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";
import { makeChatWidgetToken } from "../src/chat/widget-token";

describe("chat facade (e2e)", () => {
  let app: INestApplication;
  let upstream: http.Server;
  let received: Array<{
    method: string;
    path: string;
    body: Record<string, unknown>;
    headers: http.IncomingHttpHeaders;
  }> = [];
  let savedAnswerUrl: string | undefined;
  let savedInternalSecret: string | undefined;
  let savedWidgetSecret: string | undefined;
  let savedWidgetRateLimit: string | undefined;

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    savedAnswerUrl = process.env.ANSWER_SERVICE_URL;
    savedInternalSecret = process.env.RAKU_INTERNAL_AUTH_SECRET;
    savedWidgetSecret = process.env.RAKU_CHAT_WIDGET_SECRET;
    savedWidgetRateLimit = process.env.RAKU_CHAT_WIDGET_RATE_LIMIT_PER_MINUTE;
    process.env.RAKU_INTERNAL_AUTH_SECRET = "chat-secret"; // pragma: allowlist secret -- test-only dummy secret
    process.env.RAKU_CHAT_WIDGET_SECRET = "widget-secret"; // pragma: allowlist secret -- test-only dummy secret
    process.env.RAKU_CHAT_WIDGET_RATE_LIMIT_PER_MINUTE = "60";
    upstream = http.createServer((req, res) => {
      const url = new URL(req.url ?? "/", "http://answer-service.local");
      let data = "";
      req.on("data", (chunk) => (data += chunk));
      req.on("end", () => {
        const body = JSON.parse(data || "{}");
        received.push({ method: req.method ?? "", path: url.pathname, body, headers: req.headers });
        res.setHeader("content-type", "application/json");

        if (req.method === "POST" && url.pathname === "/internal/chat/sessions") {
          res.statusCode = 201;
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: req.headers["x-raku-tenant-id"],
              session_id: "chat_1",
              status: "waiting_user",
              processed_initial_message: true,
              user_message_id: "msg_user_1",
              assistant_message: {
                message_id: "msg_assistant_1",
                message: "登録メールアドレスを教えてください。",
                message_type: "text",
                ai_action: "collect_slot",
                quick_replies: [{ label: "人間に相談する", value: "handoff" }],
                citations: [],
              },
              state: {
                status: "waiting_user",
                response_state: "completed",
                current_intent: "cancel_subscription",
                missing_slots: ["email", "company_name"],
              },
              rag: null,
              handoff: null,
              ticket: null,
              correlation_id: "corr_chat_create",
            }),
          );
          return;
        }

        if (req.method === "POST" && url.pathname === "/internal/chat/sessions/chat_1/messages") {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: req.headers["x-raku-tenant-id"],
              session_id: "chat_1",
              status: "waiting_user",
              user_message_id: "msg_user_2",
              assistant_message: {
                message_id: "msg_assistant_2",
                message: "会社名を教えてください。",
                message_type: "text",
                ai_action: "collect_slot",
                quick_replies: [{ label: "人間に相談する", value: "handoff" }],
                citations: [],
              },
              state: { status: "waiting_user", response_state: "completed", missing_slots: ["company_name"] },
              rag: null,
              handoff: null,
              ticket: null,
              correlation_id: "corr_chat_msg",
            }),
          );
          return;
        }

        if (req.method === "PUT" && url.pathname === "/internal/chat/source-exposure-policies/pol_1") {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: req.headers["x-raku-tenant-id"],
              policy_id: "pol_1",
              source_id: body.source_id,
              collection_id: body.collection_id,
              exposure_mode: body.exposure_mode,
              status: "active",
              correlation_id: "corr_policy",
            }),
          );
          return;
        }

        if (req.method === "GET" && url.pathname === "/internal/chat/source-exposure-policies") {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: req.headers["x-raku-tenant-id"],
              items: [
                {
                  policy_id: "chat-internal:manuals",
                  source_id: "",
                  collection_id: "manuals",
                  exposure_mode: "internal_authenticated",
                  allowed_channels: ["web_chat"],
                  allowed_intents: ["rag_question"],
                  require_approved_effective: true,
                  allow_obsolete_primary_evidence: false,
                  status: "active",
                },
              ],
              correlation_id: "corr_policy_list",
            }),
          );
          return;
        }

        if (req.method === "PUT" && url.pathname === "/internal/chat/scenarios/cancel-basic/versions/csv_1") {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: req.headers["x-raku-tenant-id"],
              scenario_id: "cancel-basic",
              name: "解約基本対応",
              intents: ["cancel_subscription"],
              status: "draft",
              active_version_id: null,
              versions: [
                {
                  version_id: "csv_1",
                  status: "draft",
                  required_slots: ["email"],
                  steps: body.steps,
                },
              ],
              correlation_id: "corr_scenario_version",
            }),
          );
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
    if (savedAnswerUrl === undefined) delete process.env.ANSWER_SERVICE_URL;
    else process.env.ANSWER_SERVICE_URL = savedAnswerUrl;
    if (savedInternalSecret === undefined) delete process.env.RAKU_INTERNAL_AUTH_SECRET;
    else process.env.RAKU_INTERNAL_AUTH_SECRET = savedInternalSecret;
    if (savedWidgetSecret === undefined) delete process.env.RAKU_CHAT_WIDGET_SECRET;
    else process.env.RAKU_CHAT_WIDGET_SECRET = savedWidgetSecret;
    if (savedWidgetRateLimit === undefined) delete process.env.RAKU_CHAT_WIDGET_RATE_LIMIT_PER_MINUTE;
    else process.env.RAKU_CHAT_WIDGET_RATE_LIMIT_PER_MINUTE = savedWidgetRateLimit;
  });

  beforeEach(() => {
    received = [];
  });

  it("POST /v1/chat/sessions without auth -> 401", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/chat/sessions")
      .send({ initial_message: "解約したい" });
    expect(res.status).toBe(401);
  });

  it("creates a session through the answer-service with signed principal headers", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "alice",
      groups: ["ops"],
      roles: ["reader"],
    });
    const res = await request(app.getHttpServer())
      .post("/v1/chat/sessions")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ initial_message: "解約したい", tenant_id: "tenant_victim" });

    expect(res.status).toBe(201);
    expect(res.body.session_id).toBe("chat_1");
    expect(res.body.tenant_id).toBe("tenant_a");
    expect(received[0].method).toBe("POST");
    expect(received[0].path).toBe("/internal/chat/sessions");
    expect(received[0].headers["x-raku-tenant-id"]).toBe("tenant_a");
    expect(received[0].headers["x-raku-user-id"]).toBe("alice");
    expect(received[0].headers["x-internal-auth"]).toBe("chat-secret");
    expect(received[0].body.tenant_id).toBeUndefined();
  });

  it("submits chat turns without allowing tenant body override", async () => {
    const token = makeUserToken({ tenant_id: "tenant_a", user_id: "alice", groups: [], roles: [] });
    const res = await request(app.getHttpServer())
      .post("/v1/chat/sessions/chat_1/messages")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({ message: "user@example.com です", tenant_id: "tenant_victim" });

    expect(res.status).toBe(200);
    expect(res.body.assistant_message.ai_action).toBe("collect_slot");
    expect(received[0].path).toBe("/internal/chat/sessions/chat_1/messages");
    expect(received[0].headers["x-raku-tenant-id"]).toBe("tenant_a");
    expect(received[0].body.tenant_id).toBeUndefined();
  });

  it("creates a public widget session from signed widget context without trusting body overrides", async () => {
    const widgetToken = makeChatWidgetToken(
      {
        tenant_id: "tenant_public",
        widget_id: "widget_public",
        allowed_domains: ["https://example.com"],
        collection_id: "public-manuals",
      },
      "widget-secret",
    );

    const res = await request(app.getHttpServer())
      .post("/v1/chat/public-widget/sessions")
      .set("Origin", "https://example.com")
      .send({
        widget_token: widgetToken,
        initial_message: "料金を教えてください",
        tenant_id: "tenant_victim",
        channel: "web_chat",
        collection_id: "private-manuals",
        source_id: "private-source",
        metadata: { source_id: "private-source", acl_tags: ["internal_only"] },
      });

    expect(res.status).toBe(201);
    expect(res.body.tenant_id).toBe("tenant_public");
    expect(received[0].path).toBe("/internal/chat/sessions");
    expect(received[0].headers["x-raku-tenant-id"]).toBe("tenant_public");
    expect(received[0].headers["x-raku-user-id"]).toBe("anonymous:widget_public");
    expect(received[0].body.tenant_id).toBeUndefined();
    expect(received[0].body.channel).toBe("public_widget");
    expect(received[0].body.collection_id).toBe("public-manuals");
    expect(received[0].body.source_id).toBeUndefined();
    expect((received[0].body.metadata as Record<string, unknown>).widget_origin).toBe("https://example.com");
    expect((received[0].body.metadata as Record<string, unknown>).source_id).toBeUndefined();
  });

  it("rejects public widget sessions from domains outside the signed allowlist", async () => {
    const widgetToken = makeChatWidgetToken(
      {
        tenant_id: "tenant_public",
        widget_id: "widget_domain",
        allowed_domains: ["https://example.com"],
      },
      "widget-secret",
    );

    const res = await request(app.getHttpServer())
      .post("/v1/chat/public-widget/sessions")
      .set("Origin", "https://evil.example")
      .send({ widget_token: widgetToken, initial_message: "hello" });

    expect(res.status).toBe(403);
    expect(received).toHaveLength(0);
  });

  it("rejects public widget sessions with invalid tokens before upstream", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/chat/public-widget/sessions")
      .set("Origin", "https://example.com")
      .send({ widget_token: "not-a-valid-widget-token", initial_message: "hello" });

    expect(res.status).toBe(401);
    expect(received).toHaveLength(0);
  });

  it("rate-limits public widget session creation before upstream", async () => {
    process.env.RAKU_CHAT_WIDGET_RATE_LIMIT_PER_MINUTE = "1";
    const widgetToken = makeChatWidgetToken(
      {
        tenant_id: "tenant_public",
        widget_id: "widget_rate",
        allowed_domains: ["https://example.com"],
      },
      "widget-secret",
    );

    const first = await request(app.getHttpServer())
      .post("/v1/chat/public-widget/sessions")
      .set("Origin", "https://example.com")
      .send({ widget_token: widgetToken, initial_message: "first" });
    const second = await request(app.getHttpServer())
      .post("/v1/chat/public-widget/sessions")
      .set("Origin", "https://example.com")
      .send({ widget_token: widgetToken, initial_message: "second" });

    process.env.RAKU_CHAT_WIDGET_RATE_LIMIT_PER_MINUTE = "60";
    expect(first.status).toBe(201);
    expect(second.status).toBe(429);
    expect(received).toHaveLength(1);
  });

  it("forwards internal auth on ChatBot source exposure PUT", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "admin",
      groups: [],
      roles: ["tenant_admin"],
    });
    const res = await request(app.getHttpServer())
      .put("/v1/chat/source-exposure-policies/pol_1")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        policy_id: "pol_1",
        source_id: "public-faq",
        collection_id: "manuals",
        exposure_mode: "external_authenticated",
        tenant_id: "tenant_victim",
      });

    expect(res.status).toBe(200);
    expect(res.body.tenant_id).toBe("tenant_a");
    expect(received[0].method).toBe("PUT");
    expect(received[0].path).toBe("/internal/chat/source-exposure-policies/pol_1");
    expect(received[0].headers["x-internal-auth"]).toBe("chat-secret");
    expect(received[0].body.tenant_id).toBeUndefined();
  });

  it("lists ChatBot source exposure policies with role gate and signed principal headers", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "data-admin",
      groups: [],
      roles: ["data_admin"],
    });
    const res = await request(app.getHttpServer())
      .get("/v1/chat/source-exposure-policies")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(200);
    expect(res.body.items[0].policy_id).toBe("chat-internal:manuals");
    expect(received[0].method).toBe("GET");
    expect(received[0].path).toBe("/internal/chat/source-exposure-policies");
    expect(received[0].headers["x-raku-tenant-id"]).toBe("tenant_a");
    expect(received[0].headers["x-raku-user-id"]).toBe("data-admin");
    expect(received[0].headers["x-internal-auth"]).toBe("chat-secret");
  });

  it("forwards scenario version PUT to the answer-service", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "scenario-admin",
      groups: [],
      roles: ["scenario_admin"],
    });
    const res = await request(app.getHttpServer())
      .put("/v1/chat/scenarios/cancel-basic/versions/csv_1")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        steps: [{ id: "identify_customer", required_slots: ["email"] }],
        tenant_id: "tenant_victim",
      });

    expect(res.status).toBe(200);
    expect(received[0].method).toBe("PUT");
    expect(received[0].path).toBe("/internal/chat/scenarios/cancel-basic/versions/csv_1");
    expect(received[0].headers["x-raku-tenant-id"]).toBe("tenant_a");
    expect(received[0].body.tenant_id).toBeUndefined();
  });

  it("rejects source exposure policy changes from non-admin chat users before upstream", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "field",
      groups: [],
      roles: ["field_user"],
    });
    const res = await request(app.getHttpServer())
      .put("/v1/chat/source-exposure-policies/pol_1")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({
        policy_id: "pol_1",
        source_id: "internal-faq",
        collection_id: "manuals",
        exposure_mode: "external_authenticated",
      });

    expect(res.status).toBe(403);
    expect(received).toHaveLength(0);
  });

  it("rejects ChatBot metrics from users without ops role before upstream", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "field",
      groups: [],
      roles: ["field_user"],
    });
    const res = await request(app.getHttpServer())
      .get("/v1/chat/metrics")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token);

    expect(res.status).toBe(403);
    expect(received).toHaveLength(0);
  });

  it("rejects scenario publish from scenario admins without approver role before upstream", async () => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "scenario-admin",
      groups: [],
      roles: ["scenario_admin"],
    });
    const res = await request(app.getHttpServer())
      .post("/v1/chat/scenarios/cancel-basic/versions/v1/publish")
      .set("Authorization", "Bearer local-dev-key")
      .set("X-User-Token", token)
      .send({});

    expect(res.status).toBe(403);
    expect(received).toHaveLength(0);
  });
});
