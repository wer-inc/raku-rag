import { BadGatewayException, Body, Controller, HttpCode, Post, Req } from "@nestjs/common";
import type { Request } from "express";
import type { SearchRequest, SearchResponse } from "@raku-rag/shared";

@Controller({ path: "search", version: "1" })
export class SearchController {
  @Post()
  @HttpCode(200)
  async search(@Req() req: Request, @Body() body: SearchRequest): Promise<SearchResponse> {
    const p = req.principal!;
    const base = process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
    const payload = {
      tenant_id: p.tenant_id,
      user_id: p.user_id,
      groups: p.groups,
      roles: p.roles,
      query: body?.query ?? "",
      collection_id: body?.collection_id,
      top_k: body?.top_k,
    };
    const upstream = await fetch(`${base}/internal/search`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as SearchResponse;
  }
}
