import {
  BadGatewayException,
  Body,
  Controller,
  Get,
  HttpCode,
  NotFoundException,
  Param,
  Post,
  Req,
} from "@nestjs/common";
import type { Request } from "express";
import { internalAuthHeaders } from "../auth/internal-auth";

type JsonObject = Record<string, unknown>;

@Controller({ path: "investment", version: "1" })
export class InvestmentController {
  private baseUrl(): string {
    return process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
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

  private stripTenantOverrides(value: unknown): unknown {
    if (Array.isArray(value)) {
      return value.map((item) => this.stripTenantOverrides(item));
    }
    if (value && typeof value === "object") {
      const cleaned: JsonObject = {};
      for (const [key, child] of Object.entries(value)) {
        if (key !== "tenant_id") {
          cleaned[key] = this.stripTenantOverrides(child);
        }
      }
      return cleaned;
    }
    return value;
  }

  private async requestCore<T>(
    req: Request,
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    successStatus?: number,
  ): Promise<T> {
    const headers: Record<string, string> = { ...this.principalHeaders(req) };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
    }
    const upstream = await fetch(`${this.baseUrl()}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(this.stripTenantOverrides(body)),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (upstream.status === 404) {
      throw new NotFoundException("not found");
    }
    if (!upstream.ok || (successStatus !== undefined && upstream.status !== successStatus)) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as T;
  }

  @Post("metadata/import")
  @HttpCode(202)
  async metadataImport(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/investment/metadata/import", body, 202);
  }

  @Post("documents/enrich")
  @HttpCode(200)
  async enrichDocument(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/investment/documents/enrich", body);
  }

  @Get("funds/:fundId/knowledge")
  async fundKnowledge(@Req() req: Request, @Param("fundId") fundId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/investment/funds/${encodeURIComponent(fundId)}/knowledge`);
  }

  @Post("workflows/fund-question")
  @HttpCode(200)
  async fundQuestion(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/investment/workflows/fund-question", body);
  }

  @Post("workflows/rfp-response-draft")
  async rfpResponseDraft(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/investment/workflows/rfp-response-draft", body, 201);
  }

  @Post("workflows/ddq-response-draft")
  async ddqResponseDraft(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/investment/workflows/ddq-response-draft", body, 201);
  }

  @Post("workflows/inquiry-reply-draft")
  async inquiryReplyDraft(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/investment/workflows/inquiry-reply-draft", body, 201);
  }

  @Post("workflows/marketing-material-check")
  @HttpCode(200)
  async marketingMaterialCheck(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/investment/workflows/marketing-material-check", body);
  }

  @Post("workflows/monthly-commentary-draft")
  async monthlyCommentaryDraft(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/investment/workflows/monthly-commentary-draft", body, 201);
  }

  @Post("workflows/compliance-rule-question")
  @HttpCode(200)
  async complianceRuleQuestion(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/investment/workflows/compliance-rule-question", body);
  }

  @Get("drafts/:artifactId")
  async draft(@Req() req: Request, @Param("artifactId") artifactId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/investment/drafts/${encodeURIComponent(artifactId)}`);
  }

  @Post("drafts/:artifactId/review")
  @HttpCode(200)
  async reviewDraft(
    @Req() req: Request,
    @Param("artifactId") artifactId: string,
    @Body() body: JsonObject,
  ): Promise<JsonObject> {
    return this.requestCore(req, "POST", `/internal/investment/drafts/${encodeURIComponent(artifactId)}/review`, body);
  }

  @Post("drafts/:artifactId/compliance-review")
  @HttpCode(200)
  async complianceReview(
    @Req() req: Request,
    @Param("artifactId") artifactId: string,
    @Body() body: JsonObject,
  ): Promise<JsonObject> {
    return this.requestCore(
      req,
      "POST",
      `/internal/investment/drafts/${encodeURIComponent(artifactId)}/compliance-review`,
      body,
    );
  }

  @Get("disclosure-evidence/:artifactId")
  async disclosureEvidence(@Req() req: Request, @Param("artifactId") artifactId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/investment/disclosure-evidence/${encodeURIComponent(artifactId)}`);
  }

  @Get("dashboard")
  async dashboard(@Req() req: Request): Promise<JsonObject> {
    return this.requestCore(req, "GET", "/internal/investment/dashboard");
  }

  @Get("kpi")
  async kpi(@Req() req: Request): Promise<JsonObject> {
    return this.requestCore(req, "GET", "/internal/investment/kpi");
  }

  @Get("audit")
  async audit(@Req() req: Request): Promise<JsonObject> {
    return this.requestCore(req, "GET", "/internal/investment/audit");
  }

  @Get("governance/status")
  async governanceStatus(@Req() req: Request): Promise<JsonObject> {
    return this.requestCore(req, "GET", "/internal/investment/governance/status");
  }
}
