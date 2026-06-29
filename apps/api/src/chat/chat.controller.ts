import {
  BadGatewayException,
  Body,
  Controller,
  ForbiddenException,
  Get,
  HttpCode,
  HttpException,
  UnauthorizedException,
  Param,
  Post,
  Put,
  Query,
  Req,
} from "@nestjs/common";
import type { Request } from "express";
import type {
  ChatCreateSessionRequest,
  ChatCreateSessionResponse,
  ChatFeedbackRequest,
  ChatFeedbackResponse,
  ChatHandoffRequest,
  ChatHandoffResponse,
  ChatMessageRequest,
  ChatMessageResponse,
  ChatMetricsResponse,
  ChatSessionDetailResponse,
  ChatSessionListResponse,
  ChatScenarioResponse,
  ChatPublicWidgetSessionRequest,
  ChatbotSourceExposureListResponse,
  ChatbotSourceExposurePolicy,
  ChatbotSourceExposureValidationResponse,
} from "@raku-rag/shared";
import { internalAuthHeaders } from "../auth/internal-auth";
import { stripTenantOverrides } from "../auth/strip-tenant";
import { chatWidgetSecret, parseChatWidgetToken, type ChatWidgetClaims } from "./widget-token";

type HttpMethod = "GET" | "POST" | "PUT";

const SESSION_ADMIN_ROLES = ["ops_owner", "tenant_admin", "reviewer"];
const HANDOFF_READ_ROLES = ["operator", "ops_owner", "tenant_admin"];
const METRICS_ROLES = ["ops_owner", "tenant_admin"];
const SOURCE_POLICY_ROLES = ["tenant_admin", "scenario_admin", "data_admin"];
const SCENARIO_READ_ROLES = ["tenant_admin", "scenario_admin", "scenario_approver"];
const SCENARIO_MANAGE_ROLES = ["tenant_admin", "scenario_admin"];
const SCENARIO_APPROVE_ROLES = ["tenant_admin", "scenario_approver"];
const EXPORT_DELETE_ROLES = ["tenant_admin", "audit_admin"];

function normalizeOrigin(value: string | undefined): string | null {
  if (!value) {
    return null;
  }
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

async function forwardToChatService<T>(
  method: HttpMethod,
  internalPath: string,
  headers: Record<string, string>,
  body?: unknown,
  query?: Record<string, string>,
): Promise<T> {
  const base = process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
  const url = new URL(`${base}${internalPath}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }
  const upstream = await fetch(url, {
    method,
    headers: {
      "content-type": "application/json",
      ...headers,
    },
    body: method === "GET" ? undefined : JSON.stringify(stripTenantOverrides(body ?? {})),
  }).catch(() => {
    throw new BadGatewayException("answer-service unreachable");
  });
  if (!upstream.ok) {
    const payload = await upstream.json().catch(() => ({}));
    if (upstream.status >= 400 && upstream.status < 500) {
      throw new HttpException(payload, upstream.status);
    }
    throw new BadGatewayException(`answer-service error: ${upstream.status}`);
  }
  return (await upstream.json()) as T;
}

@Controller({ path: "chat/public-widget", version: "1" })
export class PublicChatController {
  private readonly rateCounters = new Map<string, { windowStarted: number; count: number }>();

  @Post("sessions")
  @HttpCode(201)
  async createWidgetSession(
    @Req() req: Request,
    @Body() body: ChatPublicWidgetSessionRequest,
  ): Promise<ChatCreateSessionResponse> {
    const claims = this.verifyWidgetContext(req, body);
    this.enforceRateLimit(req, claims);
    const origin = normalizeOrigin(req.header("origin"))!;
    return forwardToChatService<ChatCreateSessionResponse>(
      "POST",
      "/internal/chat/sessions",
      this.widgetPrincipalHeaders(claims),
      {
        channel: "public_widget",
        collection_id: claims.collection_id,
        initial_message: typeof body.initial_message === "string" ? body.initial_message : undefined,
        metadata: {
          chat_mode: "external_anonymous",
          widget_id: claims.widget_id,
          widget_origin: origin,
        },
      },
    );
  }

  private verifyWidgetContext(req: Request, body: ChatPublicWidgetSessionRequest): ChatWidgetClaims {
    let secret: string;
    try {
      secret = chatWidgetSecret();
    } catch {
      throw new ForbiddenException({ error: "anonymous_chat_disabled" });
    }
    const token = String(body.widget_token || req.header("x-raku-widget-token") || "");
    const claims = parseChatWidgetToken(token, secret);
    if (!claims) {
      throw new UnauthorizedException({ error: "invalid_widget_token" });
    }
    const origin = normalizeOrigin(req.header("origin"));
    const allowed = new Set(claims.allowed_domains.map((domain) => normalizeOrigin(domain)));
    if (!origin || !allowed.has(origin)) {
      throw new ForbiddenException({ error: "widget_domain_not_allowed" });
    }
    return claims;
  }

  private enforceRateLimit(req: Request, claims: ChatWidgetClaims): void {
    const limit = Number(process.env.RAKU_CHAT_WIDGET_RATE_LIMIT_PER_MINUTE ?? 60);
    if (!Number.isFinite(limit) || limit <= 0) {
      return;
    }
    const key = `${claims.tenant_id}:${claims.widget_id}:${req.ip ?? req.socket.remoteAddress ?? "unknown"}`;
    const now = Date.now();
    const existing = this.rateCounters.get(key);
    if (!existing || now - existing.windowStarted >= 60_000) {
      this.rateCounters.set(key, { windowStarted: now, count: 1 });
      return;
    }
    if (existing.count >= limit) {
      throw new HttpException({ error: "rate_limited" }, 429);
    }
    existing.count += 1;
  }

  private widgetPrincipalHeaders(claims: ChatWidgetClaims): Record<string, string> {
    return {
      "x-raku-tenant-id": claims.tenant_id,
      "x-raku-user-id": `anonymous:${claims.widget_id}`,
      "x-raku-groups": JSON.stringify(["public_widget"]),
      "x-raku-roles": JSON.stringify(["chat_anonymous"]),
      ...internalAuthHeaders(),
    };
  }
}

@Controller({ path: "chat", version: "1" })
export class ChatController {
  @Post("sessions")
  @HttpCode(201)
  async createSession(
    @Req() req: Request,
    @Body() body: ChatCreateSessionRequest,
  ): Promise<ChatCreateSessionResponse> {
    return this.forward<ChatCreateSessionResponse>(req, "POST", "/internal/chat/sessions", body);
  }

  @Get("sessions")
  async listSessions(
    @Req() req: Request,
    @Query() query: Record<string, string>,
  ): Promise<ChatSessionListResponse> {
    this.requireAnyRole(req, SESSION_ADMIN_ROLES);
    return this.forward<ChatSessionListResponse>(req, "GET", "/internal/chat/sessions", undefined, query);
  }

  @Get("sessions/:sessionId")
  async getSession(
    @Req() req: Request,
    @Param("sessionId") sessionId: string,
  ): Promise<ChatSessionDetailResponse> {
    return this.forward<ChatSessionDetailResponse>(
      req,
      "GET",
      `/internal/chat/sessions/${encodeURIComponent(sessionId)}`,
    );
  }

  @Post("sessions/:sessionId/messages")
  @HttpCode(200)
  async sendMessage(
    @Req() req: Request,
    @Param("sessionId") sessionId: string,
    @Body() body: ChatMessageRequest,
  ): Promise<ChatMessageResponse> {
    return this.forward<ChatMessageResponse>(
      req,
      "POST",
      `/internal/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
      body,
    );
  }

  @Post("sessions/:sessionId/handoff")
  @HttpCode(200)
  async requestHandoff(
    @Req() req: Request,
    @Param("sessionId") sessionId: string,
    @Body() body: ChatHandoffRequest,
  ): Promise<ChatHandoffResponse> {
    return this.forward<ChatHandoffResponse>(
      req,
      "POST",
      `/internal/chat/sessions/${encodeURIComponent(sessionId)}/handoff`,
      body,
    );
  }

  @Get("handoffs/:handoffId")
  async getHandoff(@Req() req: Request, @Param("handoffId") handoffId: string) {
    this.requireAnyRole(req, HANDOFF_READ_ROLES);
    return this.forward(
      req,
      "GET",
      `/internal/chat/handoffs/${encodeURIComponent(handoffId)}`,
    );
  }

  @Post("sessions/:sessionId/feedback")
  @HttpCode(201)
  async submitFeedback(
    @Req() req: Request,
    @Param("sessionId") sessionId: string,
    @Body() body: ChatFeedbackRequest,
  ): Promise<ChatFeedbackResponse> {
    return this.forward<ChatFeedbackResponse>(
      req,
      "POST",
      `/internal/chat/sessions/${encodeURIComponent(sessionId)}/feedback`,
      body,
    );
  }

  @Get("metrics")
  async metrics(@Req() req: Request): Promise<ChatMetricsResponse> {
    this.requireAnyRole(req, METRICS_ROLES);
    return this.forward<ChatMetricsResponse>(req, "GET", "/internal/chat/metrics");
  }

  @Post("sessions/export")
  @HttpCode(200)
  async exportSessions(@Req() req: Request) {
    this.requireAnyRole(req, EXPORT_DELETE_ROLES);
    return this.forward(req, "POST", "/internal/chat/sessions/export", {});
  }

  @Post("sessions/:sessionId/delete-request")
  @HttpCode(202)
  async deleteRequest(@Req() req: Request, @Param("sessionId") sessionId: string) {
    this.requireAnyRole(req, EXPORT_DELETE_ROLES);
    return this.forward(
      req,
      "POST",
      `/internal/chat/sessions/${encodeURIComponent(sessionId)}/delete-request`,
      {},
    );
  }

  @Get("retention-policy")
  async retentionPolicy(@Req() req: Request) {
    this.requireAnyRole(req, EXPORT_DELETE_ROLES);
    return this.forward(req, "GET", "/internal/chat/retention-policy");
  }

  @Get("source-exposure-policies")
  async listSourcePolicies(@Req() req: Request): Promise<ChatbotSourceExposureListResponse> {
    this.requireAnyRole(req, SOURCE_POLICY_ROLES);
    return this.forward<ChatbotSourceExposureListResponse>(
      req,
      "GET",
      "/internal/chat/source-exposure-policies",
    );
  }

  @Put("source-exposure-policies/:policyId")
  async upsertSourcePolicy(
    @Req() req: Request,
    @Param("policyId") policyId: string,
    @Body() body: ChatbotSourceExposurePolicy,
  ): Promise<ChatbotSourceExposurePolicy> {
    this.requireAnyRole(req, SOURCE_POLICY_ROLES);
    return this.forward<ChatbotSourceExposurePolicy>(
      req,
      "PUT",
      `/internal/chat/source-exposure-policies/${encodeURIComponent(policyId)}`,
      body,
    );
  }

  @Post("source-exposure-policies/validate")
  @HttpCode(200)
  async validateSourcePolicy(
    @Req() req: Request,
    @Body() body: Partial<ChatbotSourceExposurePolicy>,
  ): Promise<ChatbotSourceExposureValidationResponse> {
    this.requireAnyRole(req, SOURCE_POLICY_ROLES);
    return this.forward<ChatbotSourceExposureValidationResponse>(
      req,
      "POST",
      "/internal/chat/source-exposure-policies/validate",
      body,
    );
  }

  @Get("scenarios")
  async listScenarios(@Req() req: Request) {
    this.requireAnyRole(req, SCENARIO_READ_ROLES);
    return this.forward(req, "GET", "/internal/chat/scenarios");
  }

  @Post("scenarios")
  @HttpCode(201)
  async createScenario(@Req() req: Request, @Body() body: Record<string, unknown>) {
    this.requireAnyRole(req, SCENARIO_MANAGE_ROLES);
    return this.forward(req, "POST", "/internal/chat/scenarios", body);
  }

  @Put("scenarios/:scenarioId/versions/:versionId")
  async upsertScenarioVersion(
    @Req() req: Request,
    @Param("scenarioId") scenarioId: string,
    @Param("versionId") versionId: string,
    @Body() body: Record<string, unknown>,
  ): Promise<ChatScenarioResponse> {
    this.requireAnyRole(req, SCENARIO_MANAGE_ROLES);
    return this.forward<ChatScenarioResponse>(
      req,
      "PUT",
      `/internal/chat/scenarios/${encodeURIComponent(scenarioId)}/versions/${encodeURIComponent(
        versionId,
      )}`,
      body,
    );
  }

  @Post("scenarios/:scenarioId/versions/:versionId/:action")
  @HttpCode(200)
  async scenarioAction(
    @Req() req: Request,
    @Param("scenarioId") scenarioId: string,
    @Param("versionId") versionId: string,
    @Param("action") action: string,
    @Body() body: Record<string, unknown>,
  ) {
    this.requireAnyRole(
      req,
      ["approve", "publish", "schedule", "archive"].includes(action)
        ? SCENARIO_APPROVE_ROLES
        : SCENARIO_MANAGE_ROLES,
    );
    return this.forward(
      req,
      "POST",
      `/internal/chat/scenarios/${encodeURIComponent(scenarioId)}/versions/${encodeURIComponent(
        versionId,
      )}/${encodeURIComponent(action)}`,
      body,
    );
  }

  @Post("scenarios/:scenarioId/rollback")
  @HttpCode(200)
  async rollbackScenario(@Req() req: Request, @Param("scenarioId") scenarioId: string) {
    this.requireAnyRole(req, SCENARIO_APPROVE_ROLES);
    return this.forward(
      req,
      "POST",
      `/internal/chat/scenarios/${encodeURIComponent(scenarioId)}/rollback`,
      {},
    );
  }

  private principalHeaders(req: Request): Record<string, string> {
    const p = req.principal!;
    return {
      "x-raku-tenant-id": p.tenant_id,
      "x-raku-user-id": p.user_id,
      "x-raku-groups": JSON.stringify(p.groups),
      "x-raku-roles": JSON.stringify(p.roles),
      ...internalAuthHeaders(),
    };
  }

  private requireAnyRole(req: Request, allowedRoles: readonly string[]): void {
    const roles = new Set(req.principal?.roles ?? []);
    if (!allowedRoles.some((role) => roles.has(role))) {
      throw new ForbiddenException("chat_role_required");
    }
  }

  private async forward<T>(
    req: Request,
    method: HttpMethod,
    internalPath: string,
    body?: unknown,
    query?: Record<string, string>,
  ): Promise<T> {
    return forwardToChatService<T>(method, internalPath, this.principalHeaders(req), body, query);
  }
}
