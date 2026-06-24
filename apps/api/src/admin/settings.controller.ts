import {
  BadGatewayException,
  Body,
  Controller,
  Get,
  HttpCode,
  NotFoundException,
  Param,
  Post,
  Put,
  Query,
  Req,
} from "@nestjs/common";
import type { Request } from "express";
import type {
  ACLSettingsRequest,
  ACLSettingsResponse,
  AdminBudget,
  AdminDataSource,
  AdminSettingsMutationResponse,
  BudgetSettingsRequest,
  BudgetSettingsResponse,
  DataSourceUpsertRequest,
  LoggingPolicySettings,
  LoggingPolicyUpsertRequest,
  ProviderConfigAuditEvent,
  QueryProfileSettings,
  QueryProfileUpsertRequest,
} from "@raku-rag/shared";
import { assertAdminMutationAllowed } from "../auth/roles";
import { internalAuthHeaders } from "../auth/internal-auth";

@Controller({ path: "admin", version: "1" })
export class AdminSettingsController {
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

  private async requestCore<T>(
    req: Request,
    method: "GET" | "POST" | "PUT",
    path: string,
    body?: unknown,
  ): Promise<T> {
    if (method !== "GET") {
      assertAdminMutationAllowed(req);
    }
    const headers: Record<string, string> = {
      ...this.principalHeaders(req),
    };
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
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as T;
  }

  private stripTenantOverrides(value: unknown): unknown {
    if (Array.isArray(value)) {
      return value.map((item) => this.stripTenantOverrides(item));
    }
    if (value && typeof value === "object") {
      const cleaned: Record<string, unknown> = {};
      for (const [key, child] of Object.entries(value)) {
        if (key !== "tenant_id") {
          cleaned[key] = this.stripTenantOverrides(child);
        }
      }
      return cleaned;
    }
    return value;
  }

  @Get("datasources")
  async dataSources(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
  ): Promise<AdminDataSource[]> {
    const params = new URLSearchParams();
    if (collectionId) {
      params.set("collection_id", collectionId);
    }
    const query = params.toString();
    return this.requestCore(req, "GET", `/internal/admin/datasources${query ? `?${query}` : ""}`);
  }

  @Get("datasources/:source_id")
  async dataSource(@Req() req: Request, @Param("source_id") sourceId: string): Promise<AdminDataSource> {
    return this.requestCore(req, "GET", `/internal/admin/datasources/${encodeURIComponent(sourceId)}`);
  }

  @Put("datasources/:source_id")
  async upsertDataSource(
    @Req() req: Request,
    @Param("source_id") sourceId: string,
    @Body() body: DataSourceUpsertRequest,
  ): Promise<AdminSettingsMutationResponse<AdminDataSource>> {
    return this.requestCore(req, "PUT", `/internal/admin/datasources/${encodeURIComponent(sourceId)}`, body);
  }

  @Get("query-profiles")
  async queryProfiles(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
  ): Promise<QueryProfileSettings[]> {
    const params = new URLSearchParams();
    if (collectionId) {
      params.set("collection_id", collectionId);
    }
    const query = params.toString();
    return this.requestCore(req, "GET", `/internal/admin/query-profiles${query ? `?${query}` : ""}`);
  }

  @Get("query-profiles/:profile_id")
  async queryProfile(
    @Req() req: Request,
    @Param("profile_id") profileId: string,
  ): Promise<QueryProfileSettings> {
    return this.requestCore(req, "GET", `/internal/admin/query-profiles/${encodeURIComponent(profileId)}`);
  }

  @Put("query-profiles/:profile_id")
  async upsertQueryProfile(
    @Req() req: Request,
    @Param("profile_id") profileId: string,
    @Body() body: QueryProfileUpsertRequest,
  ): Promise<AdminSettingsMutationResponse<QueryProfileSettings>> {
    return this.requestCore(req, "PUT", `/internal/admin/query-profiles/${encodeURIComponent(profileId)}`, body);
  }

  @Get("logging-policies")
  async loggingPolicies(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
  ): Promise<LoggingPolicySettings[]> {
    const params = new URLSearchParams();
    if (collectionId) {
      params.set("collection_id", collectionId);
    }
    const query = params.toString();
    return this.requestCore(req, "GET", `/internal/admin/logging-policies${query ? `?${query}` : ""}`);
  }

  @Get("provider-config-audit-events")
  async providerConfigAuditEvents(
    @Req() req: Request,
    @Query("event_type") eventType?: string,
    @Query("correlation_id") correlationId?: string,
    @Query("collection_id") collectionId?: string,
  ): Promise<ProviderConfigAuditEvent[]> {
    const params = new URLSearchParams();
    if (eventType) {
      params.set("event_type", eventType);
    }
    if (correlationId) {
      params.set("correlation_id", correlationId);
    }
    if (collectionId) {
      params.set("collection_id", collectionId);
    }
    const query = params.toString();
    return this.requestCore(req, "GET", `/internal/admin/provider-config-audit-events${query ? `?${query}` : ""}`);
  }

  @Get("logging-policies/:logging_policy_id")
  async loggingPolicy(
    @Req() req: Request,
    @Param("logging_policy_id") loggingPolicyId: string,
  ): Promise<LoggingPolicySettings> {
    return this.requestCore(req, "GET", `/internal/admin/logging-policies/${encodeURIComponent(loggingPolicyId)}`);
  }

  @Put("logging-policies/:logging_policy_id")
  async upsertLoggingPolicy(
    @Req() req: Request,
    @Param("logging_policy_id") loggingPolicyId: string,
    @Body() body: LoggingPolicyUpsertRequest,
  ): Promise<AdminSettingsMutationResponse<LoggingPolicySettings>> {
    return this.requestCore(req, "PUT", `/internal/admin/logging-policies/${encodeURIComponent(loggingPolicyId)}`, body);
  }

  @Get("acl")
  async acl(@Req() req: Request): Promise<ACLSettingsResponse> {
    return this.requestCore(req, "GET", "/internal/admin/acl");
  }

  @Put("acl")
  async updateAcl(@Req() req: Request, @Body() body: ACLSettingsRequest): Promise<ACLSettingsResponse> {
    return this.requestCore(req, "PUT", "/internal/admin/acl", body);
  }

  @Get("budgets")
  async budgets(
    @Req() req: Request,
    @Query("scope_type") scopeType?: string,
    @Query("scope_id") scopeId?: string,
  ): Promise<AdminBudget[]> {
    const params = new URLSearchParams();
    if (scopeType) {
      params.set("scope_type", scopeType);
    }
    if (scopeId) {
      params.set("scope_id", scopeId);
    }
    const query = params.toString();
    return this.requestCore(req, "GET", `/internal/admin/budgets${query ? `?${query}` : ""}`);
  }

  @Put("budgets")
  async updateBudgets(
    @Req() req: Request,
    @Body() body: BudgetSettingsRequest,
  ): Promise<BudgetSettingsResponse> {
    return this.requestCore(req, "PUT", "/internal/admin/budgets", body);
  }
}
