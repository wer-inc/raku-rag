import { BadGatewayException, Injectable, NotFoundException } from "@nestjs/common";
import type { Request } from "express";
import type {
  AdminSettingsMutationResponse,
  ProviderPolicySettings,
  ProviderPolicyUpsertRequest,
  ProviderPolicyValidationRequest,
  ProviderPolicyValidationResponse,
} from "@raku-rag/shared";

@Injectable()
export class ProviderPolicyService {
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

  private async requestCore<T>(
    req: Request,
    method: "GET" | "POST" | "PUT",
    path: string,
    body?: unknown,
  ): Promise<T> {
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

  list(req: Request, collectionId?: string): Promise<ProviderPolicySettings[]> {
    const params = new URLSearchParams();
    if (collectionId) {
      params.set("collection_id", collectionId);
    }
    const query = params.toString();
    return this.requestCore(req, "GET", `/internal/admin/provider-policies${query ? `?${query}` : ""}`);
  }

  get(req: Request, providerPolicyId: string): Promise<ProviderPolicySettings> {
    return this.requestCore(req, "GET", `/internal/admin/provider-policies/${encodeURIComponent(providerPolicyId)}`);
  }

  upsert(
    req: Request,
    providerPolicyId: string,
    body: ProviderPolicyUpsertRequest,
  ): Promise<AdminSettingsMutationResponse<ProviderPolicySettings>> {
    return this.requestCore(
      req,
      "PUT",
      `/internal/admin/provider-policies/${encodeURIComponent(providerPolicyId)}`,
      body,
    );
  }

  validate(
    req: Request,
    providerPolicyId: string,
    body: ProviderPolicyValidationRequest,
  ): Promise<ProviderPolicyValidationResponse> {
    return this.requestCore(
      req,
      "POST",
      `/internal/admin/provider-policies/${encodeURIComponent(providerPolicyId)}/validate`,
      body,
    );
  }
}
