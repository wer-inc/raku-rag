import { MiddlewareConsumer, Module, NestModule } from "@nestjs/common";
import { HealthController } from "./health/health.controller";
import { WhoamiController } from "./auth/whoami.controller";
import { AnswerController } from "./answer/answer.controller";
import { AuthMiddleware } from "./auth/auth.middleware";

@Module({
  controllers: [HealthController, WhoamiController, AnswerController],
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer) {
    // Health is public; the mock auth middleware guards the protected routes only.
    consumer.apply(AuthMiddleware).forRoutes(WhoamiController, AnswerController);
  }
}
