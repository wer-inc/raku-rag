import {
  BadGatewayException,
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  NotFoundException,
  Param,
  Post,
  Query,
  Req,
} from "@nestjs/common";
import type { Request } from "express";
import type {
  AdminJobSummary,
  DataSourcePreviewRequest,
  DataSourcePreviewResponse,
  DeleteDocumentResponse,
  DocumentProcessingStatusResponse,
  IngestResponse,
  IngestionRunStatusResponse,
  ReindexRequest,
  ReindexResponse,
  SourceSyncStatusResponse,
} from "@raku-rag/shared";
import { assertAdminMutationAllowed } from "../auth/roles";
import { internalAuthHeaders } from "../auth/internal-auth";

@Controller({ path: "admin", version: "1" })
export class AdminJobsController {
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
    if (upstream.status === 404) {
      throw new NotFoundException("not found");
    }
    if (!upstream.ok) {
      throw new BadGatewayException(`answer-service error: ${upstream.status}`);
    }
    return (await upstream.json()) as T;
  }

  private async postToCore<T>(req: Request, path: string, body?: unknown): Promise<T> {
    assertAdminMutationAllowed(req);
    const headers: Record<string, string> = this.principalHeaders(req);
    if (body !== undefined) {
      headers["content-type"] = "application/json";
    }
    const upstream = await fetch(`${this.baseUrl()}${path}`, {
      method: "POST",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
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

  private async deleteFromCore<T>(req: Request, path: string): Promise<T> {
    assertAdminMutationAllowed(req);
    const upstream = await fetch(`${this.baseUrl()}${path}`, {
      method: "DELETE",
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

  @Get("sources/:source_id/sync-status")
  async sourceSyncStatus(
    @Req() req: Request,
    @Param("source_id") sourceId: string,
  ): Promise<SourceSyncStatusResponse> {
    return this.getFromCore(req, `/internal/sources/${encodeURIComponent(sourceId)}/sync-status`);
  }

  @Post("sources/:source_id/test-connection")
  async testSourceConnection(
    @Req() req: Request,
    @Param("source_id") sourceId: string,
    @Body() body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return this.postToCore(req, `/internal/sources/${encodeURIComponent(sourceId)}/test-connection`, body);
  }

  @Post("sources/:source_id/preview")
  @HttpCode(200)
  async previewSource(
    @Req() req: Request,
    @Param("source_id") sourceId: string,
    @Body() body: DataSourcePreviewRequest,
  ): Promise<DataSourcePreviewResponse> {
    return this.postToCore(req, `/internal/sources/${encodeURIComponent(sourceId)}/preview`, body);
  }

  @Post("sources/:source_id/sync")
  @HttpCode(202)
  async syncSource(
    @Req() req: Request,
    @Param("source_id") sourceId: string,
    @Body() body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return this.postToCore(req, `/internal/sources/${encodeURIComponent(sourceId)}/sync`, body);
  }

  @Get("jobs")
  async jobs(
    @Req() req: Request,
    @Query("status") status?: string,
    @Query("source_id") sourceId?: string,
  ): Promise<{ jobs: AdminJobSummary[] }> {
    const params = new URLSearchParams();
    if (status) {
      params.set("status", status);
    }
    if (sourceId) {
      params.set("source_id", sourceId);
    }
    const query = params.toString();
    return this.getFromCore(req, `/internal/jobs${query ? `?${query}` : ""}`);
  }

  @Get("ingestion-runs/:ingestion_run_id")
  async ingestionRun(
    @Req() req: Request,
    @Param("ingestion_run_id") ingestionRunId: string,
  ): Promise<IngestionRunStatusResponse> {
    return this.getFromCore(req, `/internal/ingestion-runs/${encodeURIComponent(ingestionRunId)}`);
  }

  @Post("ingestion-runs/:ingestion_run_id/retry")
  @HttpCode(202)
  async retryIngestionRun(
    @Req() req: Request,
    @Param("ingestion_run_id") ingestionRunId: string,
  ): Promise<IngestResponse> {
    return this.postToCore(req, `/internal/ingestion-runs/${encodeURIComponent(ingestionRunId)}/retry`);
  }

  @Post("collections/:collection_id/reindex")
  @HttpCode(202)
  async reindexCollection(
    @Req() req: Request,
    @Param("collection_id") collectionId: string,
    @Body() body: ReindexRequest,
  ): Promise<ReindexResponse> {
    return this.postToCore(req, `/internal/admin/collections/${encodeURIComponent(collectionId)}/reindex`, body);
  }

  @Get("documents")
  async documents(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
    @Query("approval_status") approvalStatus?: string,
  ): Promise<{ documents: Record<string, unknown>[] }> {
    const params = new URLSearchParams();
    if (collectionId) {
      params.set("collection_id", collectionId);
    }
    if (approvalStatus) {
      params.set("approval_status", approvalStatus);
    }
    const query = params.toString();
    return this.getFromCore(
      req,
      `/internal/manufacturing/documents${query ? `?${query}` : ""}`,
    );
  }

  @Get("documents/:document_id")
  async documentDetail(
    @Req() req: Request,
    @Param("document_id") documentId: string,
  ): Promise<Record<string, unknown>> {
    return this.getFromCore(
      req,
      `/internal/manufacturing/documents/${encodeURIComponent(documentId)}`,
    );
  }

  @Get("documents/:document_id/file")
  async documentFile(
    @Req() req: Request,
    @Param("document_id") documentId: string,
  ): Promise<Record<string, unknown>> {
    return this.getFromCore(
      req,
      `/internal/documents/${encodeURIComponent(documentId)}/file`,
    );
  }

  @Get("documents/:document_id/citation-view")
  async documentCitationView(
    @Req() req: Request,
    @Param("document_id") documentId: string,
    @Query("chunk_id") chunkId?: string,
  ): Promise<Record<string, unknown>> {
    const params = new URLSearchParams();
    if (chunkId) {
      params.set("chunk_id", chunkId);
    }
    const query = params.toString();
    return this.getFromCore(
      req,
      `/internal/documents/${encodeURIComponent(documentId)}/citation-view${query ? `?${query}` : ""}`,
    );
  }

  @Get("documents/:document_id/processing-status")
  async documentProcessingStatus(
    @Req() req: Request,
    @Param("document_id") documentId: string,
  ): Promise<DocumentProcessingStatusResponse> {
    return this.getFromCore(req, `/internal/documents/${encodeURIComponent(documentId)}/processing-status`);
  }

  @Delete("documents/:document_id")
  @HttpCode(202)
  async deleteDocument(
    @Req() req: Request,
    @Param("document_id") documentId: string,
  ): Promise<DeleteDocumentResponse> {
    return this.deleteFromCore(req, `/internal/documents/${encodeURIComponent(documentId)}`);
  }
}
