import { MiddlewareConsumer, Module, NestModule } from "@nestjs/common";
import { HealthController } from "./health/health.controller";
import { WhoamiController } from "./auth/whoami.controller";
import { AnswerController } from "./answer/answer.controller";
import { ManufacturingController } from "./manufacturing/manufacturing.controller";
import { SearchController } from "./search/search.controller";
import { IngestController } from "./ingest/ingest.controller";
import { UploadsController } from "./ingest/uploads.controller";
import { AdminJobsController } from "./admin/jobs.controller";
import { AdminSettingsController } from "./admin/settings.controller";
import { ProviderPoliciesController } from "./admin/provider-policies.controller";
import { RetrievalProfilesController } from "./admin/retrieval-profiles.controller";
import { EvalController } from "./eval/eval.controller";
import { FeedbackController } from "./feedback/feedback.controller";
import { AssetsController } from "./assets/assets.controller";
import { IndustriesController } from "./industries/industries.controller";
import { OpenApiController } from "./openapi/openapi.controller";
import { RealEstateController } from "./real-estate/real-estate.controller";
import { InvestmentController } from "./investment/investment.controller";
import { OAuthController } from "./connectors/oauth.controller";
import { ChatController, PublicChatController } from "./chat/chat.controller";
import { PhoneController } from "./phone/phone.controller";
import { AuthMiddleware } from "./auth/auth.middleware";
import { ProviderPolicyService } from "./provider-policy/provider-policy.service";
import { RetrievalProfileService } from "./retrieval/retrieval-profile.service";
import { BedrockGuardrailsAdapter } from "./guardrails/bedrock-guardrails.adapter";
import { BedrockClaudeService } from "./llm/bedrock-claude.service";
import { LangfuseExporter } from "./observability/langfuse";
import { LoggingPolicyEnforcer } from "./observability/logging-policy.service";
import { BedrockCohereRerankService } from "./rerank/bedrock-cohere-rerank.service";

@Module({
  controllers: [
    HealthController,
    WhoamiController,
    AnswerController,
    ManufacturingController,
    SearchController,
    IngestController,
    UploadsController,
    AdminJobsController,
    AdminSettingsController,
    ProviderPoliciesController,
    RetrievalProfilesController,
    EvalController,
    FeedbackController,
    AssetsController,
    IndustriesController,
    RealEstateController,
    InvestmentController,
    OAuthController,
    ChatController,
    PublicChatController,
    PhoneController,
    OpenApiController,
  ],
  providers: [
    ProviderPolicyService,
    RetrievalProfileService,
    BedrockGuardrailsAdapter,
    BedrockClaudeService,
    LoggingPolicyEnforcer,
    LangfuseExporter,
    BedrockCohereRerankService,
  ],
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer) {
    // Health is public; the mock auth middleware guards the protected routes only.
    consumer
      .apply(AuthMiddleware)
      .forRoutes(
        WhoamiController,
        AnswerController,
        ManufacturingController,
        SearchController,
        IngestController,
        UploadsController,
        AdminJobsController,
        AdminSettingsController,
        ProviderPoliciesController,
        RetrievalProfilesController,
        EvalController,
        FeedbackController,
        AssetsController,
        IndustriesController,
        RealEstateController,
        InvestmentController,
        OAuthController,
        ChatController,
        PhoneController,
      );
  }
}
