import { BadGatewayException, HttpException } from "@nestjs/common";
import type { Request } from "express";
import { internalAuthHeaders } from "../auth/internal-auth";
import { stripTenantOverrides } from "../auth/strip-tenant";

type HttpMethod = "GET" | "POST" | "PUT";

/**
 * 022-ai-phone-rag — thin forwarding seam to the answer-service /internal/phone/* surface.
 * Identity travels ONLY via x-raku-* headers derived from the signed principal; tenant/user
 * overrides in request bodies are stripped before forwarding (spec: no body overrides).
 */
export class PhoneForwardingService {
  async forward<T>(
    req: Request,
    method: HttpMethod,
    internalPath: string,
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
        ...this.principalHeaders(req),
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
}
