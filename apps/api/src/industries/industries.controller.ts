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

@Controller({ path: "industries", version: "1" })
export class IndustriesController {
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

  @Get()
  async list(@Req() req: Request): Promise<JsonObject> {
    return this.requestCore(req, "GET", "/internal/industries");
  }

  @Get(":industryId/profile")
  async profile(@Req() req: Request, @Param("industryId") industryId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/industries/${encodeURIComponent(industryId)}/profile`);
  }

  @Post(":industryId/metadata/validate")
  @HttpCode(200)
  async validateMetadata(
    @Req() req: Request,
    @Param("industryId") industryId: string,
    @Body() body: JsonObject,
  ): Promise<JsonObject> {
    return this.requestCore(req, "POST", `/internal/industries/${encodeURIComponent(industryId)}/metadata/validate`, body);
  }

  @Post(":industryId/documents/enrich")
  @HttpCode(200)
  async enrichDocument(
    @Req() req: Request,
    @Param("industryId") industryId: string,
    @Body() body: JsonObject,
  ): Promise<JsonObject> {
    return this.requestCore(req, "POST", `/internal/industries/${encodeURIComponent(industryId)}/documents/enrich`, body);
  }

  @Post(":industryId/workflows/:workflowId/run")
  @HttpCode(200)
  async runWorkflow(
    @Req() req: Request,
    @Param("industryId") industryId: string,
    @Param("workflowId") workflowId: string,
    @Body() body: JsonObject,
  ): Promise<JsonObject> {
    return this.requestCore(
      req,
      "POST",
      `/internal/industries/${encodeURIComponent(industryId)}/workflows/${encodeURIComponent(workflowId)}/run`,
      body,
    );
  }

  @Post(":industryId/drafts/:artifactId/review")
  @HttpCode(200)
  async reviewDraft(
    @Req() req: Request,
    @Param("industryId") industryId: string,
    @Param("artifactId") artifactId: string,
    @Body() body: JsonObject,
  ): Promise<JsonObject> {
    return this.requestCore(
      req,
      "POST",
      `/internal/industries/${encodeURIComponent(industryId)}/drafts/${encodeURIComponent(artifactId)}/review`,
      body,
    );
  }

  @Post(":industryId/drafts/:artifactType")
  async createDraft(
    @Req() req: Request,
    @Param("industryId") industryId: string,
    @Param("artifactType") artifactType: string,
    @Body() body: JsonObject,
  ): Promise<JsonObject> {
    return this.requestCore(
      req,
      "POST",
      `/internal/industries/${encodeURIComponent(industryId)}/drafts/${encodeURIComponent(artifactType)}`,
      body,
      201,
    );
  }

  @Get(":industryId/drafts/:artifactId")
  async draft(
    @Req() req: Request,
    @Param("industryId") industryId: string,
    @Param("artifactId") artifactId: string,
  ): Promise<JsonObject> {
    return this.requestCore(
      req,
      "GET",
      `/internal/industries/${encodeURIComponent(industryId)}/drafts/${encodeURIComponent(artifactId)}`,
    );
  }

  @Get(":industryId/dashboard")
  async dashboard(@Req() req: Request, @Param("industryId") industryId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/industries/${encodeURIComponent(industryId)}/dashboard`);
  }

  @Get(":industryId/kpi")
  async kpi(@Req() req: Request, @Param("industryId") industryId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/industries/${encodeURIComponent(industryId)}/kpi`);
  }

  @Get(":industryId/governance/status")
  async governanceStatus(@Req() req: Request, @Param("industryId") industryId: string): Promise<JsonObject> {
    return this.requestCore(req, "GET", `/internal/industries/${encodeURIComponent(industryId)}/governance/status`);
  }
}
