import {
  BadGatewayException,
  Body,
  Controller,
  Get,
  HttpCode,
  NotFoundException,
  Post,
  Req,
} from "@nestjs/common";
import type { Request } from "express";
import { assertAdminMutationAllowed } from "../auth/roles";
import { internalAuthHeaders } from "../auth/internal-auth";
import { stripTenantOverrides } from "../auth/strip-tenant";

/**
 * ADR-018 §12 — extraction/visual review queue: forwards to the answer-service `/internal/reviews/*`
 * endpoints. Read (queue + metrics) is available to any authenticated principal; applying a decision
 * is an admin/ops mutation (`assertAdminMutationAllowed`).
 */
@Controller({ path: "reviews", version: "1" })
export class ReviewsController {
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

  private async getFromCore<T>(req: Request, path: string): Promise<T> {
    const upstream = await fetch(`${this.baseUrl()}${path}`, {
      headers: this.principalHeaders(req),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as T;
  }

  @Get("extraction")
  async listExtractionReviews(@Req() req: Request): Promise<{ items: unknown[] }> {
    return this.getFromCore(req, "/internal/reviews/extraction");
  }

  @Get("extraction/metrics")
  async extractionMetrics(@Req() req: Request): Promise<Record<string, unknown>> {
    return this.getFromCore(req, "/internal/reviews/extraction/metrics");
  }

  @Post("extraction/actions")
  @HttpCode(200)
  async applyExtractionReviewAction(
    @Req() req: Request,
    @Body() body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    assertAdminMutationAllowed(req);
    const upstream = await fetch(`${this.baseUrl()}/internal/reviews/extraction/actions`, {
      method: "POST",
      headers: { ...this.principalHeaders(req), "content-type": "application/json" },
      body: JSON.stringify(stripTenantOverrides(body)),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (upstream.status === 404) {
      throw new NotFoundException("review chunk not found");
    }
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as Record<string, unknown>;
  }
}
