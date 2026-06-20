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

type JsonObject = Record<string, unknown>;

@Controller({ path: "real-estate", version: "1" })
export class RealEstateController {
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
    return this.requestCore(req, "POST", "/internal/real-estate/metadata/import", body, 202);
  }

  @Post("documents/enrich")
  @HttpCode(200)
  async enrichDocument(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/real-estate/documents/enrich", body);
  }

  @Get("properties/:propertyId/knowledge")
  async propertyKnowledge(@Req() req: Request, @Param("propertyId") propertyId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/real-estate/properties/${encodeURIComponent(propertyId)}/knowledge`);
  }

  @Get("units/:unitId/knowledge")
  async unitKnowledge(@Req() req: Request, @Param("unitId") unitId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/real-estate/units/${encodeURIComponent(unitId)}/knowledge`);
  }

  @Post("workflows/contract-question")
  @HttpCode(200)
  async contractQuestion(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/real-estate/workflows/contract-question", body);
  }

  @Post("workflows/repair-investigation")
  @HttpCode(200)
  async repairInvestigation(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/real-estate/workflows/repair-investigation", body);
  }

  @Post("workflows/occupant-reply-draft")
  async occupantReplyDraft(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/real-estate/workflows/occupant-reply-draft", body, 201);
  }

  @Post("workflows/owner-report-draft")
  async ownerReportDraft(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/real-estate/workflows/owner-report-draft", body, 201);
  }

  @Post("workflows/move-out-checklist-draft")
  async moveOutChecklistDraft(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/real-estate/workflows/move-out-checklist-draft", body, 201);
  }

  @Post("workflows/restoration-explanation-draft")
  async restorationExplanationDraft(@Req() req: Request, @Body() body: JsonObject): Promise<JsonObject> {
    return this.requestCore(req, "POST", "/internal/real-estate/workflows/restoration-explanation-draft", body, 201);
  }

  @Get("drafts/:artifactId")
  async draft(@Req() req: Request, @Param("artifactId") artifactId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/real-estate/drafts/${encodeURIComponent(artifactId)}`);
  }

  @Post("drafts/:artifactId/review")
  @HttpCode(200)
  async reviewDraft(
    @Req() req: Request,
    @Param("artifactId") artifactId: string,
    @Body() body: JsonObject,
  ): Promise<JsonObject> {
    return this.requestCore(req, "POST", `/internal/real-estate/drafts/${encodeURIComponent(artifactId)}/review`, body);
  }

  @Get("dashboard")
  async dashboard(@Req() req: Request): Promise<JsonObject> {
    return this.requestCore(req, "GET", "/internal/real-estate/dashboard");
  }

  @Get("kpi")
  async kpi(@Req() req: Request): Promise<JsonObject> {
    return this.requestCore(req, "GET", "/internal/real-estate/kpi");
  }

  @Get("audit")
  async audit(@Req() req: Request): Promise<JsonObject> {
    return this.requestCore(req, "GET", "/internal/real-estate/audit");
  }

  @Get("governance/status")
  async governanceStatus(@Req() req: Request): Promise<JsonObject> {
    return this.requestCore(req, "GET", "/internal/real-estate/governance/status");
  }
}
