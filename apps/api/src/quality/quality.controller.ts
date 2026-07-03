import { BadGatewayException, Controller, Get, Query, Req } from "@nestjs/common";
import type { Request } from "express";
import type { QualityOperationalResponse } from "@raku-rag/shared";
import { internalAuthHeaders } from "../auth/internal-auth";
import { assertReviewViewAllowed } from "../auth/roles";

// ★G3b/★G5: 実測運用メトリクス for the 品質・KPI screen — real p50/p95/未回答 drill-down from
// query_traces plus the persisted low-rating count. Thin proxy like the feedback controller:
// authz (reviewer/admin) at this facade; tenancy is enforced below from the forwarded principal.
@Controller({ path: "quality", version: "1" })
export class QualityController {
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

  // Reviewer/admin only (same read gate as the feedback list / review queue); tenant scope comes
  // from the signed principal forwarded as headers, never from the query string.
  @Get("operational")
  async operationalSummary(
    @Req() req: Request,
    @Query("limit") limit?: string,
  ): Promise<QualityOperationalResponse> {
    assertReviewViewAllowed(req);
    const base = process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
    const params = new URLSearchParams();
    if (limit) {
      params.set("limit", limit);
    }
    const query = params.toString();
    const upstream = await fetch(`${base}/internal/quality/operational${query ? `?${query}` : ""}`, {
      method: "GET",
      headers: this.principalHeaders(req),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as QualityOperationalResponse;
  }
}
