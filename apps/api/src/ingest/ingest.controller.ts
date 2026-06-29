import { BadGatewayException, Body, Controller, HttpCode, Post, Req } from "@nestjs/common";
import type { Request } from "express";
import type { IngestRequest, IngestResponse } from "@raku-rag/shared";
import { internalAuthHeaders } from "../auth/internal-auth";
import { assertDocumentRefOwnedByTenant } from "./s3-ref-ownership";

@Controller({ path: "ingest", version: "1" })
export class IngestController {
  @Post()
  @HttpCode(202)
  async ingest(@Req() req: Request, @Body() body: IngestRequest): Promise<IngestResponse> {
    const p = req.principal!;
    assertDocumentRefOwnedByTenant(body?.ref, p.tenant_id);
    const base = process.env.ANSWER_SERVICE_URL ?? "http://127.0.0.1:8088";
    const payload = {
      tenant_id: p.tenant_id,
      user_id: p.user_id,
      groups: p.groups,
      roles: p.roles,
      collection_id: body?.collection_id,
      source_id: body?.source_id,
      document_id: body?.document_id,
      document_ref: body?.ref,
      content_type: body?.content_type ?? "text/plain",
      // P1-1: forward optional manufacturing approval/safety metadata so the answer-service persists
      // it on the Document (the safety overlay resolves approval state from there).
      manufacturing: body?.manufacturing,
    };
    const upstream = await fetch(`${base}/internal/ingest`, {
      method: "POST",
      headers: { "content-type": "application/json", ...internalAuthHeaders() },
      body: JSON.stringify(payload),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as IngestResponse;
  }
}
