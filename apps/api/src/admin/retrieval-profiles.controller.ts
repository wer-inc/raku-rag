import { Body, Controller, Get, HttpCode, Param, Post, Put, Query, Req } from "@nestjs/common";
import type { Request } from "express";
import type {
  AdminSettingsMutationResponse,
  RetrievalProfileBenchmarkRequest,
  RetrievalProfileBenchmarkResponse,
  RetrievalProfileSettings,
  RetrievalProfileUpsertRequest,
} from "@raku-rag/shared";
import { RetrievalProfileService } from "../retrieval/retrieval-profile.service";

@Controller({ path: "admin/retrieval-profiles", version: "1" })
export class RetrievalProfilesController {
  constructor(private readonly profiles: RetrievalProfileService) {}

  @Get()
  async retrievalProfiles(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
  ): Promise<RetrievalProfileSettings[]> {
    return this.profiles.list(req, collectionId);
  }

  @Get(":retrieval_profile_id")
  async retrievalProfile(
    @Req() req: Request,
    @Param("retrieval_profile_id") retrievalProfileId: string,
  ): Promise<RetrievalProfileSettings> {
    return this.profiles.get(req, retrievalProfileId);
  }

  @Put(":retrieval_profile_id")
  async upsertRetrievalProfile(
    @Req() req: Request,
    @Param("retrieval_profile_id") retrievalProfileId: string,
    @Body() body: RetrievalProfileUpsertRequest,
  ): Promise<AdminSettingsMutationResponse<RetrievalProfileSettings>> {
    return this.profiles.upsert(req, retrievalProfileId, body);
  }

  @Post(":retrieval_profile_id/benchmark")
  @HttpCode(202)
  async benchmarkRetrievalProfile(
    @Req() req: Request,
    @Param("retrieval_profile_id") retrievalProfileId: string,
    @Body() body: RetrievalProfileBenchmarkRequest,
  ): Promise<RetrievalProfileBenchmarkResponse> {
    return this.profiles.benchmark(req, retrievalProfileId, body);
  }
}
