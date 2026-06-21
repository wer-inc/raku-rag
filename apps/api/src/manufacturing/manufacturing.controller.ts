import { BadGatewayException, Body, Controller, HttpCode, Post, Req } from "@nestjs/common";
import type { Request } from "express";

/**
 * P1-1 — `/v1/manufacturing/answer` product facade. THIN HTTP boundary: AuthMiddleware authenticates
 * the caller and attaches `req.principal`; this controller forwards to the Python answer-service
 * `/internal/manufacturing/answer`, which runs the manufacturing safety overlay (high-risk gate,
 * approved+effective evidence requirement, draft/obsolete never primary) over the RAG-truth system.
 * No retrieval/ACL/ranking/safety logic is reimplemented here.
 *
 * Security invariant: tenant + identity come from the SIGNED principal, never the request body.
 */
interface ManufacturingAnswerRequest {
  query?: string;
  collection_id?: string;
  intent_hint?: string;
  manufacturing_filters?: Record<string, unknown>;
}

@Controller({ path: "manufacturing", version: "1" })
export class ManufacturingController {
  @Post("answer")
  @HttpCode(200)
  async answer(
    @Req() req: Request,
    @Body() body: ManufacturingAnswerRequest,
  ): Promise<Record<string, unknown>> {
    const p = req.principal!; // AuthMiddleware guarantees a principal on this route
    const base = process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
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
    const upstream = await fetch(`${base}/internal/manufacturing/answer`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as Record<string, unknown>;
  }
}
