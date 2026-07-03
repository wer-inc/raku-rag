import { BadGatewayException, Body, Controller, Get, HttpCode, Post, Query, Req } from "@nestjs/common";
import type { Request } from "express";
import type { FeedbackListResponse, FeedbackRequest, FeedbackResponse } from "@raku-rag/shared";
import { internalAuthHeaders } from "../auth/internal-auth";
import { assertReviewViewAllowed } from "../auth/roles";

@Controller({ path: "feedback", version: "1" })
export class FeedbackController {
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

  @Post()
  @HttpCode(202)
  async createFeedback(@Req() req: Request, @Body() body: FeedbackRequest): Promise<FeedbackResponse> {
    const base = process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
    const upstream = await fetch(`${base}/internal/feedback`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...this.principalHeaders(req),
      },
      body: JSON.stringify(body),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as FeedbackResponse;
  }

  // ★G3a: server-driven improvement queue — list the persisted feedback rows. Reviewer/admin
  // only (same read gate as the review queue); tenant scope comes from the signed principal
  // forwarded as headers, never from the query string.
  @Get()
  async listFeedback(
    @Req() req: Request,
    @Query("limit") limit?: string,
    @Query("offset") offset?: string,
    @Query("rating") rating?: string,
  ): Promise<FeedbackListResponse> {
    assertReviewViewAllowed(req);
    const base = process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
    const params = new URLSearchParams();
    if (limit) {
      params.set("limit", limit);
    }
    if (offset) {
      params.set("offset", offset);
    }
    if (rating) {
      params.set("rating", rating);
    }
    const query = params.toString();
    const upstream = await fetch(`${base}/internal/feedback${query ? `?${query}` : ""}`, {
      method: "GET",
      headers: this.principalHeaders(req),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as FeedbackListResponse;
  }
}
