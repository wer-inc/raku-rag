import { BadGatewayException, Body, Controller, HttpCode, Post, Req } from "@nestjs/common";
import type { Request } from "express";
import type { FeedbackRequest, FeedbackResponse } from "@raku-rag/shared";
import { internalAuthHeaders } from "../auth/internal-auth";

@Controller({ path: "feedback", version: "1" })
export class FeedbackController {
  @Post()
  @HttpCode(202)
  async createFeedback(@Req() req: Request, @Body() body: FeedbackRequest): Promise<FeedbackResponse> {
    const p = req.principal!;
    const base = process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
    const upstream = await fetch(`${base}/internal/feedback`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-raku-tenant-id": p.tenant_id,
        "x-raku-user-id": p.user_id,
        "x-raku-groups": JSON.stringify(p.groups),
        "x-raku-roles": JSON.stringify(p.roles),
        ...internalAuthHeaders(),
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
}
