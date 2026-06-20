import {
  BadGatewayException,
  Body,
  Controller,
  Get,
  HttpCode,
  NotFoundException,
  Param,
  Post,
  Req,
} from "@nestjs/common";
import type { Request } from "express";
import type {
  EvaluationRunCreateRequest,
  EvaluationRunCreateResponse,
  EvaluationRunStatusResponse,
  EvaluationSetCreateRequest,
  EvaluationSetCreateResponse,
} from "@raku-rag/shared";

@Controller({ path: "evaluations", version: "1" })
export class EvalController {
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

  private async postToCore<T>(req: Request, path: string, body: unknown): Promise<T> {
    const upstream = await fetch(`${this.baseUrl()}${path}`, {
      method: "POST",
      headers: { ...this.principalHeaders(req), "content-type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => {
      throw new BadGatewayException("answer-service unreachable");
    });
    if (upstream.status === 404) {
      throw new NotFoundException("not found");
    }
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as T;
  }

  private async getFromCore<T>(req: Request, path: string): Promise<T> {
    const upstream = await fetch(`${this.baseUrl()}${path}`, {
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
    return (await upstream.json()) as T;
  }

  @Post("sets")
  async createSet(@Req() req: Request, @Body() body: EvaluationSetCreateRequest): Promise<EvaluationSetCreateResponse> {
    return this.postToCore(req, "/internal/evaluations/sets", body);
  }

  @Post("runs")
  @HttpCode(202)
  async createRun(@Req() req: Request, @Body() body: EvaluationRunCreateRequest): Promise<EvaluationRunCreateResponse> {
    return this.postToCore(req, "/internal/evaluations/runs", body);
  }

  @Get("runs/:run_id")
  async runStatus(@Req() req: Request, @Param("run_id") runId: string): Promise<EvaluationRunStatusResponse> {
    return this.getFromCore(req, `/internal/evaluations/runs/${encodeURIComponent(runId)}`);
  }
}
