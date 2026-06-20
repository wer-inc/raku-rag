import { BadGatewayException, Controller, Get, NotFoundException, Param, Req } from "@nestjs/common";
import type { Request } from "express";
import type { VisualAssetResponse } from "@raku-rag/shared";

@Controller({ path: "assets", version: "1" })
export class AssetsController {
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

  @Get(":asset_id")
  async asset(@Req() req: Request, @Param("asset_id") assetId: string): Promise<VisualAssetResponse> {
    const upstream = await fetch(`${this.baseUrl()}/internal/assets/${encodeURIComponent(assetId)}`, {
      headers: this.principalHeaders(req),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (upstream.status === 404) {
      throw new NotFoundException("not found");
    }
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as VisualAssetResponse;
  }
}
