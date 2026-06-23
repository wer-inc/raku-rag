import {
  BadGatewayException,
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
import type { ManufacturingAnswerRequest, ManufacturingAnswerResponse } from "@raku-rag/shared";
import { assertAdminMutationAllowed } from "../auth/roles";

/**
 * P1-1 — `/v1/manufacturing/answer` product facade. THIN HTTP boundary: AuthMiddleware authenticates
 * the caller and attaches `req.principal`; this controller forwards to the Python answer-service
 * `/internal/manufacturing/answer`, which runs the manufacturing safety overlay (high-risk gate,
 * approved+effective evidence requirement, draft/obsolete never primary) over the RAG-truth system.
 * No retrieval/ACL/ranking/safety logic is reimplemented here.
 *
 * Security invariant: tenant + identity come from the SIGNED principal, never the request body.
 */
type JsonObject = Record<string, unknown>;

function queryPath(path: string, query: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") {
      params.set(key, value);
    }
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

@Controller({ path: "manufacturing", version: "1" })
export class ManufacturingController {
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
    method: "GET" | "POST" | "PUT",
    path: string,
    body?: unknown,
    stripBodyTenantOverrides = true,
  ): Promise<T> {
    const headers: Record<string, string> = { ...this.principalHeaders(req) };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
    }
    const upstream = await fetch(`${this.baseUrl()}${path}`, {
      method,
      headers,
      body:
        body === undefined
          ? undefined
          : JSON.stringify(stripBodyTenantOverrides ? this.stripTenantOverrides(body) : body),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as T;
  }

  @Post("answer")
  @HttpCode(200)
  async answer(
    @Req() req: Request,
    @Body() body: ManufacturingAnswerRequest,
  ): Promise<ManufacturingAnswerResponse> {
    const p = req.principal!; // AuthMiddleware guarantees a principal on this route
    const payload = {
      tenant_id: p.tenant_id,
      user_id: p.user_id,
      groups: p.groups,
      roles: p.roles,
      query: body?.query ?? "",
      collection_id: body?.collection_id,
      intent_hint: body?.intent_hint,
      manufacturing_filters: body?.manufacturing_filters,
    };
    return this.requestCore<ManufacturingAnswerResponse>(
      req,
      "POST",
      "/internal/manufacturing/answer",
      payload,
      false,
    );
  }

  @Get("policy/data-use")
  async dataUsePolicy(@Req() req: Request): Promise<Record<string, unknown>> {
    return this.requestCore(req, "GET", "/internal/manufacturing/policy/data-use");
  }

  @Post("sources/:sourceId/sync")
  @HttpCode(202)
  async requestSourceSync(
    @Req() req: Request,
    @Param("sourceId") sourceId: string,
    @Body() body: JsonObject,
  ): Promise<Record<string, unknown>> {
    assertAdminMutationAllowed(req);
    return this.requestCore(
      req,
      "POST",
      `/internal/manufacturing/sources/${encodeURIComponent(sourceId)}/sync`,
      body,
    );
  }

  @Get("sources/:sourceId/sync-status")
  async sourceSyncStatus(
    @Req() req: Request,
    @Param("sourceId") sourceId: string,
  ): Promise<Record<string, unknown>> {
    return this.requestCore(
      req,
      "GET",
      `/internal/manufacturing/sources/${encodeURIComponent(sourceId)}/sync-status`,
    );
  }

  @Get("ingestion-runs/:runId")
  async ingestionRun(
    @Req() req: Request,
    @Param("runId") runId: string,
  ): Promise<Record<string, unknown>> {
    return this.requestCore(
      req,
      "GET",
      `/internal/manufacturing/ingestion-runs/${encodeURIComponent(runId)}`,
    );
  }

  @Put("documents/:documentId/metadata")
  async updateDocumentMetadata(
    @Req() req: Request,
    @Param("documentId") documentId: string,
    @Body() body: JsonObject,
  ): Promise<Record<string, unknown>> {
    assertAdminMutationAllowed(req);
    return this.requestCore(
      req,
      "PUT",
      `/internal/manufacturing/documents/${encodeURIComponent(documentId)}/metadata`,
      body,
    );
  }

  @Post("documents/:documentId/approval")
  @HttpCode(200)
  async updateDocumentApproval(
    @Req() req: Request,
    @Param("documentId") documentId: string,
    @Body() body: JsonObject,
  ): Promise<Record<string, unknown>> {
    assertAdminMutationAllowed(req);
    return this.requestCore(
      req,
      "POST",
      `/internal/manufacturing/documents/${encodeURIComponent(documentId)}/approval`,
      body,
    );
  }

  @Post("trouble-cases/search")
  @HttpCode(200)
  async searchTroubleCases(
    @Req() req: Request,
    @Body() body: JsonObject,
  ): Promise<Record<string, unknown>> {
    return this.requestCore(req, "POST", "/internal/manufacturing/trouble-cases/search", body);
  }

  @Post("drafts")
  @HttpCode(200)
  async createDraft(
    @Req() req: Request,
    @Body() body: JsonObject,
  ): Promise<Record<string, unknown>> {
    return this.requestCore(req, "POST", "/internal/manufacturing/drafts", body);
  }

  @Get("drafts/:artifactId")
  async draft(
    @Req() req: Request,
    @Param("artifactId") artifactId: string,
  ): Promise<Record<string, unknown>> {
    return this.requestCore(
      req,
      "GET",
      `/internal/manufacturing/drafts/${encodeURIComponent(artifactId)}`,
    );
  }

  @Post("drafts/:artifactId/assign")
  @HttpCode(200)
  async assignDraft(
    @Req() req: Request,
    @Param("artifactId") artifactId: string,
    @Body() body: JsonObject,
  ): Promise<Record<string, unknown>> {
    assertAdminMutationAllowed(req);
    return this.requestCore(
      req,
      "POST",
      `/internal/manufacturing/drafts/${encodeURIComponent(artifactId)}/assign`,
      body,
    );
  }

  @Post("drafts/:artifactId/review")
  @HttpCode(200)
  async reviewDraft(
    @Req() req: Request,
    @Param("artifactId") artifactId: string,
    @Body() body: JsonObject,
  ): Promise<Record<string, unknown>> {
    assertAdminMutationAllowed(req);
    return this.requestCore(
      req,
      "POST",
      `/internal/manufacturing/drafts/${encodeURIComponent(artifactId)}/review`,
      body,
    );
  }

  @Get("documents")
  async documents(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
  ): Promise<Record<string, unknown>> {
    return this.requestCore(
      req,
      "GET",
      queryPath("/internal/manufacturing/documents", { collection_id: collectionId }),
    );
  }

  @Get("dashboard")
  async dashboard(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
    @Query("factory_id") factoryId?: string,
    @Query("department_id") departmentId?: string,
    @Query("from") from?: string,
    @Query("to") to?: string,
  ): Promise<Record<string, unknown>> {
    return this.requestCore(
      req,
      "GET",
      queryPath("/internal/manufacturing/dashboard", {
        collection_id: collectionId,
        factory_id: factoryId,
        department_id: departmentId,
        from,
        to,
      }),
    );
  }

  @Get("safety-telemetry")
  async safetyTelemetry(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
    @Query("factory_id") factoryId?: string,
    @Query("department_id") departmentId?: string,
    @Query("from") from?: string,
    @Query("to") to?: string,
    @Query("granularity") granularity?: string,
  ): Promise<Record<string, unknown>> {
    return this.requestCore(
      req,
      "GET",
      queryPath("/internal/manufacturing/safety-telemetry", {
        collection_id: collectionId,
        factory_id: factoryId,
        department_id: departmentId,
        from,
        to,
        granularity,
      }),
    );
  }

  @Get("kpi")
  async kpi(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
    @Query("from") from?: string,
    @Query("to") to?: string,
    @Query("format") format?: string,
  ): Promise<Record<string, unknown>> {
    return this.requestCore(
      req,
      "GET",
      queryPath("/internal/manufacturing/kpi", {
        collection_id: collectionId,
        from,
        to,
        format,
      }),
    );
  }

  @Put("policy/data-use")
  async updateDataUsePolicy(
    @Req() req: Request,
    @Body() body: JsonObject,
  ): Promise<Record<string, unknown>> {
    assertAdminMutationAllowed(req);
    return this.requestCore(req, "PUT", "/internal/manufacturing/policy/data-use", body);
  }

  @Get("governance/status")
  async governanceStatus(@Req() req: Request): Promise<Record<string, unknown>> {
    return this.requestCore(req, "GET", "/internal/manufacturing/governance/status");
  }

  @Get("audit/export")
  async auditExport(
    @Req() req: Request,
    @Query("fmt") fmt?: string,
  ): Promise<Record<string, unknown>> {
    const path = fmt
      ? `/internal/manufacturing/audit/export?fmt=${encodeURIComponent(fmt)}`
      : "/internal/manufacturing/audit/export";
    return this.requestCore(req, "GET", path);
  }
}
