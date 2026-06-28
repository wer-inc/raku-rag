import { BadGatewayException, Body, Controller, HttpCode, Post, Req } from "@nestjs/common";
import type { Request } from "express";
import type { AnswerRequest, AnswerResponse } from "@raku-rag/shared";
import { internalAuthHeaders } from "../auth/internal-auth";

/**
 * Step 4a — `/v1/answer` product facade. This is a THIN HTTP boundary: AuthMiddleware authenticates the
 * caller and attaches `req.principal`; this controller forwards the query to the Python answer-service,
 * which owns the RAG truth (retrieval / ACL / ranking) over the Postgres + pgvector + RLS ProductionSystem.
 * No retrieval, ACL, ranking, or manufacturing safety logic is reimplemented here.
 *
 * In the manufacturing product, the legacy generic `/v1/answer` route is a compatibility alias for the
 * safety-aware answer path. This prevents older clients and smoke tests from bypassing high-risk,
 * approved-evidence, draft, and obsolete-document gates that `/v1/manufacturing/answer` enforces.
 *
 * Security invariant: tenant + identity come from the SIGNED principal, never from the request body — a
 * body-supplied `tenant_id` is ignored, so a caller can never query another tenant through this facade.
 */
@Controller({ path: "answer", version: "1" })
export class AnswerController {
  @Post()
  @HttpCode(200)
  async answer(@Req() req: Request, @Body() body: AnswerRequest): Promise<AnswerResponse> {
    const p = req.principal!; // AuthMiddleware guarantees a principal on this route
    const base = process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
    const payload = {
      tenant_id: p.tenant_id,
      user_id: p.user_id,
      groups: p.groups,
      roles: p.roles,
      query: body?.query ?? "",
      collection_id: body?.collection_id,
    };
    const upstream = await fetch(`${base}/internal/manufacturing/answer`, {
      method: "POST",
      headers: { "content-type": "application/json", ...internalAuthHeaders() },
      body: JSON.stringify(payload),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as AnswerResponse;
  }
}
