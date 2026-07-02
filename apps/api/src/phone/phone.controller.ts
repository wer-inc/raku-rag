import {
  Body,
  Controller,
  Get,
  HttpCode,
  Param,
  Post,
  Put,
  Query,
  Req,
} from "@nestjs/common";
import type { Request } from "express";
import type {
  PhoneCallDetailResponse,
  PhoneCallListResponse,
  PhoneHandoffAcceptRequest,
  PhoneHandoffAcceptResponse,
  PhoneHandoffResponse,
  PhoneScenarioCreateRequest,
  PhoneScenarioListResponse,
  PhoneScenarioMutationResponse,
  PhoneScenarioPreviewRequest,
  PhoneScenarioPreviewResponse,
  PhoneScenarioVersionRequest,
  PhoneSimulateCallRequest,
  PhoneSimulateCallResponse,
  PhoneTurnRequest,
  PhoneTurnResponse,
} from "@raku-rag/shared";
import {
  PHONE_CALL_READ_ROLES,
  PHONE_DELETE_ROLES,
  PHONE_HANDOFF_READ_ROLES,
  PHONE_LIFECYCLE_ROLES,
  PHONE_METRICS_ROLES,
  PHONE_QA_ROLES,
  PHONE_SCENARIO_APPROVE_ROLES,
  PHONE_SCENARIO_MANAGE_ROLES,
  PHONE_SCENARIO_READ_ROLES,
  PHONE_SIMULATE_ROLES,
  assertAnyRoleAllowed,
} from "../auth/roles";
import { PhoneForwardingService } from "./phone.service";

const SCENARIO_APPROVER_ACTIONS = new Set(["approve", "publish", "schedule", "archive"]);

/**
 * 022-ai-phone-rag — public /v1/phone/* facade (contracts/phone-rag-openapi.md).
 * Thin proxy: authorization gate here, orchestration/safety/tenancy in the answer-service
 * phone layer. Identity always derives from the signed principal, never the body.
 */
@Controller({ path: "phone", version: "1" })
export class PhoneController {
  private readonly forwarding = new PhoneForwardingService();

  @Post("calls/simulate")
  @HttpCode(202)
  async simulateCall(
    @Req() req: Request,
    @Body() body: PhoneSimulateCallRequest,
  ): Promise<PhoneSimulateCallResponse> {
    assertAnyRoleAllowed(req, PHONE_SIMULATE_ROLES);
    return this.forwarding.forward(req, "POST", "/internal/phone/calls/simulate", body);
  }

  @Post("calls/:callId/turns")
  @HttpCode(200)
  async submitTurn(
    @Req() req: Request,
    @Param("callId") callId: string,
    @Body() body: PhoneTurnRequest,
  ): Promise<PhoneTurnResponse> {
    assertAnyRoleAllowed(req, PHONE_SIMULATE_ROLES);
    return this.forwarding.forward(
      req,
      "POST",
      `/internal/phone/calls/${encodeURIComponent(callId)}/turns`,
      body,
    );
  }

  @Get("calls")
  async listCalls(
    @Req() req: Request,
    @Query() query: Record<string, string>,
  ): Promise<PhoneCallListResponse> {
    assertAnyRoleAllowed(req, PHONE_CALL_READ_ROLES);
    return this.forwarding.forward(req, "GET", "/internal/phone/calls", undefined, query);
  }

  @Get("calls/:callId")
  async getCall(
    @Req() req: Request,
    @Param("callId") callId: string,
  ): Promise<PhoneCallDetailResponse> {
    assertAnyRoleAllowed(req, PHONE_CALL_READ_ROLES);
    return this.forwarding.forward(
      req,
      "GET",
      `/internal/phone/calls/${encodeURIComponent(callId)}`,
    );
  }

  // --- US4/US5: quality reviews, metrics, retention/export/deletion ------------------------

  @Post("calls/:callId/quality-evaluations")
  @HttpCode(201)
  async createQualityEvaluation(
    @Req() req: Request,
    @Param("callId") callId: string,
    @Body() body: Record<string, unknown>,
  ) {
    assertAnyRoleAllowed(req, PHONE_QA_ROLES);
    return this.forwarding.forward(
      req,
      "POST",
      `/internal/phone/calls/${encodeURIComponent(callId)}/quality-evaluations`,
      body,
    );
  }

  @Get("calls/:callId/quality-evaluations")
  async listQualityEvaluations(@Req() req: Request, @Param("callId") callId: string) {
    assertAnyRoleAllowed(req, PHONE_QA_ROLES);
    return this.forwarding.forward(
      req,
      "GET",
      `/internal/phone/calls/${encodeURIComponent(callId)}/quality-evaluations`,
    );
  }

  @Get("metrics")
  async metrics(@Req() req: Request, @Query() query: Record<string, string>) {
    assertAnyRoleAllowed(req, PHONE_METRICS_ROLES);
    return this.forwarding.forward(req, "GET", "/internal/phone/metrics", undefined, query);
  }

  @Get("retention-policy")
  async retentionPolicy(@Req() req: Request) {
    assertAnyRoleAllowed(req, PHONE_LIFECYCLE_ROLES);
    return this.forwarding.forward(req, "GET", "/internal/phone/retention-policy");
  }

  @Post("calls/export")
  @HttpCode(202)
  async exportCalls(@Req() req: Request, @Body() body: Record<string, unknown>) {
    assertAnyRoleAllowed(req, PHONE_LIFECYCLE_ROLES);
    return this.forwarding.forward(req, "POST", "/internal/phone/calls/export", body);
  }

  @Post("calls/:callId/delete-request")
  @HttpCode(202)
  async deleteCallRequest(
    @Req() req: Request,
    @Param("callId") callId: string,
    @Body() body: Record<string, unknown>,
  ) {
    assertAnyRoleAllowed(req, PHONE_DELETE_ROLES);
    return this.forwarding.forward(
      req,
      "POST",
      `/internal/phone/calls/${encodeURIComponent(callId)}/delete-request`,
      body,
    );
  }

  @Get("handoffs/:handoffId")
  async getHandoff(
    @Req() req: Request,
    @Param("handoffId") handoffId: string,
  ): Promise<PhoneHandoffResponse> {
    assertAnyRoleAllowed(req, PHONE_HANDOFF_READ_ROLES);
    return this.forwarding.forward(
      req,
      "GET",
      `/internal/phone/handoffs/${encodeURIComponent(handoffId)}`,
    );
  }

  @Post("handoffs/:handoffId/accept")
  @HttpCode(200)
  async acceptHandoff(
    @Req() req: Request,
    @Param("handoffId") handoffId: string,
    @Body() body: PhoneHandoffAcceptRequest,
  ): Promise<PhoneHandoffAcceptResponse> {
    assertAnyRoleAllowed(req, PHONE_HANDOFF_READ_ROLES);
    return this.forwarding.forward(
      req,
      "POST",
      `/internal/phone/handoffs/${encodeURIComponent(handoffId)}/accept`,
      body,
    );
  }

  @Get("scenarios")
  async listScenarios(@Req() req: Request): Promise<PhoneScenarioListResponse> {
    assertAnyRoleAllowed(req, PHONE_SCENARIO_READ_ROLES);
    return this.forwarding.forward(req, "GET", "/internal/phone/scenarios");
  }

  @Post("scenarios")
  @HttpCode(201)
  async createScenario(
    @Req() req: Request,
    @Body() body: PhoneScenarioCreateRequest,
  ): Promise<PhoneScenarioMutationResponse> {
    assertAnyRoleAllowed(req, PHONE_SCENARIO_MANAGE_ROLES);
    return this.forwarding.forward(req, "POST", "/internal/phone/scenarios", body);
  }

  @Put("scenarios/:scenarioId/versions/:versionId")
  async upsertScenarioVersion(
    @Req() req: Request,
    @Param("scenarioId") scenarioId: string,
    @Param("versionId") versionId: string,
    @Body() body: PhoneScenarioVersionRequest,
  ): Promise<PhoneScenarioMutationResponse> {
    assertAnyRoleAllowed(req, PHONE_SCENARIO_MANAGE_ROLES);
    return this.forwarding.forward(
      req,
      "PUT",
      `/internal/phone/scenarios/${encodeURIComponent(scenarioId)}/versions/${encodeURIComponent(
        versionId,
      )}`,
      body,
    );
  }

  @Post("scenarios/:scenarioId/versions/:versionId/test")
  @HttpCode(200)
  async previewScenario(
    @Req() req: Request,
    @Param("scenarioId") scenarioId: string,
    @Param("versionId") versionId: string,
    @Body() body: PhoneScenarioPreviewRequest,
  ): Promise<PhoneScenarioPreviewResponse> {
    assertAnyRoleAllowed(req, [...PHONE_SCENARIO_MANAGE_ROLES, ...PHONE_SCENARIO_APPROVE_ROLES]);
    return this.forwarding.forward(
      req,
      "POST",
      `/internal/phone/scenarios/${encodeURIComponent(scenarioId)}/versions/${encodeURIComponent(
        versionId,
      )}/test`,
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
  ): Promise<PhoneScenarioMutationResponse> {
    assertAnyRoleAllowed(
      req,
      SCENARIO_APPROVER_ACTIONS.has(action)
        ? PHONE_SCENARIO_APPROVE_ROLES
        : PHONE_SCENARIO_MANAGE_ROLES,
    );
    return this.forwarding.forward(
      req,
      "POST",
      `/internal/phone/scenarios/${encodeURIComponent(scenarioId)}/versions/${encodeURIComponent(
        versionId,
      )}/${encodeURIComponent(action)}`,
      body,
    );
  }

  @Post("scenarios/:scenarioId/rollback")
  @HttpCode(200)
  async rollbackScenario(
    @Req() req: Request,
    @Param("scenarioId") scenarioId: string,
    @Body() body: Record<string, unknown>,
  ): Promise<PhoneScenarioMutationResponse> {
    assertAnyRoleAllowed(req, PHONE_SCENARIO_APPROVE_ROLES);
    return this.forwarding.forward(
      req,
      "POST",
      `/internal/phone/scenarios/${encodeURIComponent(scenarioId)}/rollback`,
      body,
    );
  }
}
