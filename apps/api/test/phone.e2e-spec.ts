import { INestApplication } from "@nestjs/common";
import request from "supertest";
import * as http from "http";
import type { AddressInfo } from "net";
import { createApp } from "../src/main";
import { makeUserToken } from "../src/auth/principal";

/**
 * T029/T041/T050/T053 — /v1/phone/* facade e2e: role gates, forwarding, identity from signed
 * principal headers (never body), internal auth header propagation, scenario role split.
 */
describe("phone facade (e2e)", () => {
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

  beforeAll(async () => {
    process.env.NODE_ENV = "test";
    savedAnswerUrl = process.env.ANSWER_SERVICE_URL;
    savedInternalSecret = process.env.RAKU_INTERNAL_AUTH_SECRET;
    process.env.RAKU_INTERNAL_AUTH_SECRET = "phone-secret"; // pragma: allowlist secret -- test-only dummy secret

    upstream = http.createServer((req, res) => {
      const url = new URL(req.url ?? "/", "http://answer-service.local");
      let data = "";
      req.on("data", (chunk) => (data += chunk));
      req.on("end", () => {
        const body = JSON.parse(data || "{}");
        received.push({ method: req.method ?? "", path: url.pathname, body, headers: req.headers });
        res.setHeader("content-type", "application/json");
        const tenant = req.headers["x-raku-tenant-id"];

        if (req.method === "POST" && url.pathname === "/internal/phone/calls/simulate") {
          res.statusCode = 202;
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: tenant,
              call_id: "call_1",
              status: "active",
              status_url: "/v1/phone/calls/call_1",
              turns: [
                {
                  api_version: "v1",
                  tenant_id: tenant,
                  call_id: "call_1",
                  turn_id: "turn_002",
                  call_state: "active",
                  ai_action: "answer_with_citations",
                  ai_response_text: "本日の営業時間は9時から18時です。",
                  tts_audio_ref: "deterministic://tts/call_1/turn_002",
                  citations: [
                    {
                      source_id: "faq",
                      document_id: "FAQ-HOURS",
                      chunk_id: "FAQ-HOURS:0",
                      version: "3",
                      retrieval_score: 0.91,
                      approval_status: "approved",
                    },
                  ],
                  handoff: null,
                  safety: { answered_with_evidence: true, blocked_reason: null },
                  correlation_id: "corr_sim",
                },
              ],
              correlation_id: "corr_sim",
            }),
          );
          return;
        }

        if (req.method === "POST" && url.pathname === "/internal/phone/calls/call_1/turns") {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: tenant,
              call_id: "call_1",
              turn_id: "turn_004",
              call_state: "handoff_pending",
              ai_action: "handoff",
              ai_response_text: "担当者におつなぎします。",
              tts_audio_ref: "deterministic://tts/call_1/turn_004",
              citations: [],
              handoff: {
                handoff_package_id: "handoff_1",
                reason: "customer_requested_human",
                destination_type: "queue",
                destination_id: "general-support",
                status: "queued",
              },
              safety: { answered_with_evidence: false, blocked_reason: null },
              correlation_id: "corr_turn",
            }),
          );
          return;
        }

        if (req.method === "GET" && url.pathname === "/internal/phone/handoffs/handoff_1") {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: tenant,
              handoff_package_id: "handoff_1",
              call_id: "call_1",
              status: "queued",
              reason: "customer_requested_human",
              priority: "normal",
              destination_type: "queue",
              destination_id: "general-support",
              customer: { customer_id: "cust_1", phone_number_masked: "+81******1234" },
              summary: "営業時間の問い合わせ後に転送希望",
              transcript_excerpt_redacted: "顧客: 人につないでください",
              confirmed_slots: {},
              citations: [],
              sentiment: "neutral",
              recommended_next_action: "引き継ぎ内容を確認してください。",
              correlation_id: "corr_handoff",
            }),
          );
          return;
        }

        if (
          req.method === "POST" &&
          url.pathname === "/internal/phone/handoffs/handoff_1/accept"
        ) {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: tenant,
              handoff_package_id: "handoff_1",
              status: "accepted",
              accepted_at: "2026-07-02T00:00:00Z",
              correlation_id: "corr_accept",
            }),
          );
          return;
        }

        if (req.method === "GET" && url.pathname === "/internal/phone/scenarios") {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: tenant,
              items: [
                {
                  scenario_id: "faq-basic",
                  name: "FAQ基本対応",
                  intent: "faq",
                  status: "published",
                  active_version_id: "scv_1",
                  updated_at: "2026-07-02T00:00:00Z",
                },
              ],
              correlation_id: "corr_scn_list",
            }),
          );
          return;
        }

        if (
          req.method === "POST" &&
          url.pathname === "/internal/phone/scenarios/faq-basic/rollback"
        ) {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: tenant,
              scenario_id: "faq-basic",
              active_version_id: "scv_2",
              rollback_target_version_id: body.target_version_id,
              status: "published",
              correlation_id: "corr_rollback",
            }),
          );
          return;
        }

        if (req.method === "POST" && url.pathname === "/internal/phone/scenarios") {
          res.statusCode = 201;
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: tenant,
              scenario_id: "faq-basic",
              status: "draft",
              active_version_id: null,
              correlation_id: "corr_scn",
            }),
          );
          return;
        }

        if (
          req.method === "PUT" &&
          url.pathname === "/internal/phone/scenarios/faq-basic/versions/scv_1"
        ) {
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: tenant,
              scenario_id: "faq-basic",
              scenario_version_id: "scv_1",
              status: "draft",
              correlation_id: "corr_scn_v",
            }),
          );
          return;
        }

        if (
          req.method === "POST" &&
          url.pathname.startsWith("/internal/phone/scenarios/faq-basic/versions/scv_1/")
        ) {
          const action = url.pathname.split("/").pop();
          if (action === "test") {
            res.end(
              JSON.stringify({
                api_version: "v1",
                tenant_id: tenant,
                scenario_id: "faq-basic",
                scenario_version_id: "scv_1",
                turns: [
                  { ai_action: "ask_clarification", ai_response_text: "ご契約番号を教えてください。", citations: [] },
                ],
                would_handoff: false,
                correlation_id: "corr_test",
              }),
            );
            return;
          }
          const status =
            action === "approve"
              ? "approved"
              : action === "publish"
                ? "published"
                : action === "schedule"
                  ? "scheduled"
                  : action === "archive"
                    ? "archived"
                    : "in_review";
          res.end(
            JSON.stringify({
              api_version: "v1",
              tenant_id: tenant,
              scenario_id: "faq-basic",
              scenario_version_id: "scv_1",
              status,
              active_version_id: action === "publish" ? "scv_1" : undefined,
              scheduled_publish_at: action === "schedule" ? body.publish_at : undefined,
              correlation_id: `corr_${action}`,
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
  });

  beforeEach(() => {
    received = [];
  });

  const authed = (roles: string[]) => {
    const token = makeUserToken({
      tenant_id: "tenant_a",
      user_id: "alice",
      groups: [],
      roles,
    });
    return { auth: "Bearer local-dev-key", token };
  };

  it("POST /v1/phone/calls/simulate without auth -> 401", async () => {
    const res = await request(app.getHttpServer())
      .post("/v1/phone/calls/simulate")
      .send({ utterances: [] });
    expect(res.status).toBe(401);
  });

  it("simulate requires a phone simulate role", async () => {
    const { auth, token } = authed(["reader"]);
    const res = await request(app.getHttpServer())
      .post("/v1/phone/calls/simulate")
      .set("Authorization", auth)
      .set("X-User-Token", token)
      .send({ utterances: [{ type: "speech", text: "営業時間は？" }] });
    expect(res.status).toBe(403);
    expect(received).toHaveLength(0);
  });

  it("simulates a call with signed principal headers and no tenant body override", async () => {
    const { auth, token } = authed(["tenant_admin"]);
    const res = await request(app.getHttpServer())
      .post("/v1/phone/calls/simulate")
      .set("Authorization", auth)
      .set("X-User-Token", token)
      .send({
        tenant_id: "tenant_victim",
        caller: { phone_number: "+81300001234" },
        utterances: [{ type: "speech", text: "営業時間を教えてください" }],
      });

    expect(res.status).toBe(202);
    expect(res.body.call_id).toBe("call_1");
    expect(res.body.tenant_id).toBe("tenant_a");
    expect(res.body.turns[0].ai_action).toBe("answer_with_citations");
    expect(res.body.turns[0].citations[0].document_id).toBe("FAQ-HOURS");
    expect(received[0].path).toBe("/internal/phone/calls/simulate");
    expect(received[0].headers["x-raku-tenant-id"]).toBe("tenant_a");
    expect(received[0].headers["x-raku-user-id"]).toBe("alice");
    expect(received[0].headers["x-internal-auth"]).toBe("phone-secret");
    expect(received[0].body.tenant_id).toBeUndefined();
  });

  it("POST /v1/phone/calls/{id}/turns forwards handoff decision (US2)", async () => {
    const { auth, token } = authed(["ops_owner"]);
    const res = await request(app.getHttpServer())
      .post("/v1/phone/calls/call_1/turns")
      .set("Authorization", auth)
      .set("X-User-Token", token)
      .send({ event_type: "speech", text: "人につないでください" });

    expect(res.status).toBe(200);
    expect(res.body.ai_action).toBe("handoff");
    expect(res.body.handoff.reason).toBe("customer_requested_human");
    expect(res.body.call_state).toBe("handoff_pending");
  });

  it("handoff read requires operator-tier role and forwards when allowed", async () => {
    const denied = authed(["qa_reviewer"]);
    const deniedRes = await request(app.getHttpServer())
      .get("/v1/phone/handoffs/handoff_1")
      .set("Authorization", denied.auth)
      .set("X-User-Token", denied.token);
    expect(deniedRes.status).toBe(403);

    const allowed = authed(["operator"]);
    const res = await request(app.getHttpServer())
      .get("/v1/phone/handoffs/handoff_1")
      .set("Authorization", allowed.auth)
      .set("X-User-Token", allowed.token);
    expect(res.status).toBe(200);
    expect(res.body.reason).toBe("customer_requested_human");
    expect(res.body.customer.phone_number_masked).toBe("+81******1234");
  });

  it("accepts a handoff (US2)", async () => {
    const { auth, token } = authed(["operator"]);
    const res = await request(app.getHttpServer())
      .post("/v1/phone/handoffs/handoff_1/accept")
      .set("Authorization", auth)
      .set("X-User-Token", token)
      .send({ operator_id: "op_1", queue_id: "general-support" });
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("accepted");
  });

  it("scenario draft management requires scenario admin, not approver (T053)", async () => {
    const approverOnly = authed(["scenario_approver"]);
    const deniedRes = await request(app.getHttpServer())
      .post("/v1/phone/scenarios")
      .set("Authorization", approverOnly.auth)
      .set("X-User-Token", approverOnly.token)
      .send({ name: "FAQ基本対応", intent: "faq" });
    expect(deniedRes.status).toBe(403);

    const admin = authed(["scenario_admin"]);
    const res = await request(app.getHttpServer())
      .post("/v1/phone/scenarios")
      .set("Authorization", admin.auth)
      .set("X-User-Token", admin.token)
      .send({ name: "FAQ基本対応", intent: "faq" });
    expect(res.status).toBe(201);
    expect(res.body.scenario_id).toBe("faq-basic");

    const upd = await request(app.getHttpServer())
      .put("/v1/phone/scenarios/faq-basic/versions/scv_1")
      .set("Authorization", admin.auth)
      .set("X-User-Token", admin.token)
      .send({ fallback_message: "確認して担当者におつなぎします。" });
    expect(upd.status).toBe(200);
  });

  it("approve/publish require scenario approver, not admin (T053)", async () => {
    const admin = authed(["scenario_admin"]);
    const deniedRes = await request(app.getHttpServer())
      .post("/v1/phone/scenarios/faq-basic/versions/scv_1/approve")
      .set("Authorization", admin.auth)
      .set("X-User-Token", admin.token)
      .send({});
    expect(deniedRes.status).toBe(403);

    const approver = authed(["scenario_approver"]);
    const approveRes = await request(app.getHttpServer())
      .post("/v1/phone/scenarios/faq-basic/versions/scv_1/approve")
      .set("Authorization", approver.auth)
      .set("X-User-Token", approver.token)
      .send({});
    expect(approveRes.status).toBe(200);
    expect(approveRes.body.status).toBe("approved");

    const publishRes = await request(app.getHttpServer())
      .post("/v1/phone/scenarios/faq-basic/versions/scv_1/publish")
      .set("Authorization", approver.auth)
      .set("X-User-Token", approver.token)
      .send({});
    expect(publishRes.status).toBe(200);
    expect(publishRes.body.status).toBe("published");
    expect(publishRes.body.active_version_id).toBe("scv_1");
  });

  it("submit-review stays with scenario admin (manage tier)", async () => {
    const admin = authed(["scenario_admin"]);
    const res = await request(app.getHttpServer())
      .post("/v1/phone/scenarios/faq-basic/versions/scv_1/submit-review")
      .set("Authorization", admin.auth)
      .set("X-User-Token", admin.token)
      .send({});
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("in_review");
  });

  it("lists scenarios for scenario-tier roles (T050)", async () => {
    const { auth, token } = authed(["scenario_admin"]);
    const res = await request(app.getHttpServer())
      .get("/v1/phone/scenarios")
      .set("Authorization", auth)
      .set("X-User-Token", token);
    expect(res.status).toBe(200);
    expect(res.body.items[0].scenario_id).toBe("faq-basic");
  });

  it("runs a preview test conversation (T050)", async () => {
    const { auth, token } = authed(["scenario_admin"]);
    const res = await request(app.getHttpServer())
      .post("/v1/phone/scenarios/faq-basic/versions/scv_1/test")
      .set("Authorization", auth)
      .set("X-User-Token", token)
      .send({ utterances: ["請求金額について知りたい"] });
    expect(res.status).toBe(200);
    expect(res.body.would_handoff).toBe(false);
    expect(res.body.turns[0].ai_action).toBe("ask_clarification");
  });

  it("schedules and archives with approver role (T050)", async () => {
    const approver = authed(["scenario_approver"]);
    const scheduleRes = await request(app.getHttpServer())
      .post("/v1/phone/scenarios/faq-basic/versions/scv_1/schedule")
      .set("Authorization", approver.auth)
      .set("X-User-Token", approver.token)
      .send({ publish_at: "2026-07-10T00:00:00Z" });
    expect(scheduleRes.status).toBe(200);
    expect(scheduleRes.body.status).toBe("scheduled");
    expect(scheduleRes.body.scheduled_publish_at).toBe("2026-07-10T00:00:00Z");

    const archiveRes = await request(app.getHttpServer())
      .post("/v1/phone/scenarios/faq-basic/versions/scv_1/archive")
      .set("Authorization", approver.auth)
      .set("X-User-Token", approver.token)
      .send({});
    expect(archiveRes.status).toBe(200);
    expect(archiveRes.body.status).toBe("archived");
  });

  it("rollback requires approver and forwards target version (T050)", async () => {
    const admin = authed(["scenario_admin"]);
    const deniedRes = await request(app.getHttpServer())
      .post("/v1/phone/scenarios/faq-basic/rollback")
      .set("Authorization", admin.auth)
      .set("X-User-Token", admin.token)
      .send({ target_version_id: "scv_1" });
    expect(deniedRes.status).toBe(403);

    const approver = authed(["scenario_approver"]);
    const res = await request(app.getHttpServer())
      .post("/v1/phone/scenarios/faq-basic/rollback")
      .set("Authorization", approver.auth)
      .set("X-User-Token", approver.token)
      .send({ target_version_id: "scv_1" });
    expect(res.status).toBe(200);
    expect(res.body.rollback_target_version_id).toBe("scv_1");
    expect(res.body.active_version_id).toBe("scv_2");
  });

  it("call history requires a call-read role", async () => {
    const { auth, token } = authed(["operator"]);
    const res = await request(app.getHttpServer())
      .get("/v1/phone/calls")
      .set("Authorization", auth)
      .set("X-User-Token", token);
    expect(res.status).toBe(403);
  });
});
