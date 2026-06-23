import { Body, Controller, Get, HttpCode, Param, Post, Put, Query, Req } from "@nestjs/common";
import type { Request } from "express";
import type {
  AdminSettingsMutationResponse,
  ProviderPolicySettings,
  ProviderPolicyUpsertRequest,
  ProviderPolicyValidationRequest,
  ProviderPolicyValidationResponse,
} from "@raku-rag/shared";
import { assertAdminMutationAllowed } from "../auth/roles";
import { ProviderPolicyService } from "../provider-policy/provider-policy.service";

@Controller({ path: "admin/provider-policies", version: "1" })
export class ProviderPoliciesController {
  constructor(private readonly policies: ProviderPolicyService) {}

  @Get()
  async providerPolicies(
    @Req() req: Request,
    @Query("collection_id") collectionId?: string,
  ): Promise<ProviderPolicySettings[]> {
    return this.policies.list(req, collectionId);
  }

  @Get(":provider_policy_id")
  async providerPolicy(
    @Req() req: Request,
    @Param("provider_policy_id") providerPolicyId: string,
  ): Promise<ProviderPolicySettings> {
    return this.policies.get(req, providerPolicyId);
  }

  @Put(":provider_policy_id")
  async upsertProviderPolicy(
    @Req() req: Request,
    @Param("provider_policy_id") providerPolicyId: string,
    @Body() body: ProviderPolicyUpsertRequest,
  ): Promise<AdminSettingsMutationResponse<ProviderPolicySettings>> {
    assertAdminMutationAllowed(req);
    return this.policies.upsert(req, providerPolicyId, body);
  }

  @Post(":provider_policy_id/validate")
  @HttpCode(200)
  async validateProviderPolicy(
    @Req() req: Request,
    @Param("provider_policy_id") providerPolicyId: string,
    @Body() body: ProviderPolicyValidationRequest,
  ): Promise<ProviderPolicyValidationResponse> {
    return this.policies.validate(req, providerPolicyId, body);
  }
}
