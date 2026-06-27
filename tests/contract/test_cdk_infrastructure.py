from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CdkInfrastructureContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = (ROOT / "infra/cdk/lib/raku-rag-stack.ts").read_text(encoding="utf-8")
        self.readme = (ROOT / "infra/cdk/README.md").read_text(encoding="utf-8")
        self.bin = (ROOT / "infra/cdk/bin/raku-rag.ts").read_text(encoding="utf-8")

    def test_required_aws_resources_are_declared(self) -> None:
        for token in (
            "ecsPatterns.ApplicationLoadBalancedFargateService",
            "NestjsApiService",
            "ecs.FargateService",
            "PythonWorkerService",
            "LangfuseService",
            "rds.DatabaseCluster",
            "serverlessV2",
            "AuroraPgvectorCluster",
            "sqs.Queue",
            "IngestionDeadLetterQueue",
            "s3.Bucket",
            "cognito.UserPool",
            "CfnUserPoolGroup",
            "sales_demo",
            "kms.Key",
            "secretsmanager.Secret",
            "cloudwatch.Dashboard",
            "cloudwatch.Alarm",
            "wafv2.CfnWebACL",
            "ApiWebAcl",
            "wafv2.CfnWebACLAssociation",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)

    def test_pgvector_and_security_defaults_are_explicit(self) -> None:
        for token in (
            "CREATE EXTENSION IF NOT EXISTS vector",
            "storageEncrypted: true",
            "encryptionMasterKey: dataKey",
            "LANGFUSE_LOG_RAW_CONTEXT",
            '"false"',
            "blockPublicAccess",
            "enforceSSL",
            "deadLetterQueue",
            "deadLetterQueue.grantSendMessages",
            "SQS_DLQ_URL",
            "SQS_MAX_RECEIVE_COUNT",
            "AWSManagedRulesCommonRuleSet",
            "IpRateLimit",
            "UserTokenRateLimit",
            'aggregateKeyType: "IP"',
            'aggregateKeyType: "CUSTOM_KEYS"',
            'name: "x-user-token"',
            "ApiWebAclAssociation",
            "API WAF allowed vs blocked requests",
            "API WAF rate-limit blocks",
            'namespace: "AWS/WAFV2"',
            "ApiTarget5xxAlarm",
            "IngestionDlqVisibleAlarm",
            "IngestionQueueAgeAlarm",
            "AuroraCpuAlarm",
            "ApiWafRateLimitBlockedAlarm",
            "CloudWatchAlarmNames",
            "treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)

    def test_worker_service_is_long_running_and_has_dlq_projection(self) -> None:
        for token in (
            "workers.ingest.worker --serve",
            "SQS_QUEUE_URL",
            "SQS_DLQ_URL",
            "deadLetterQueue.queueUrl",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)

    def test_answer_service_is_wired_over_real_images(self) -> None:
        # The Python answer-service must be a deployed ECS service the API proxies to, and the app
        # containers must build from the real Dockerfiles (not placeholder base images).
        for token in (
            "AnswerService",
            "apps/answer-service/Dockerfile",
            "ANSWER_SERVICE_URL",
            "ContainerImage.fromAsset",
            "apps/api/Dockerfile",
            "workers/ingest/Dockerfile",
            "InternalAuthSecret",
            "RAKU_INTERNAL_AUTH_SECRET",
            "grantBedrockInvoke",
            "bedrock:InvokeModel",
            "POSTGRES_URL",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)

    def test_visual_provider_runtime_context_and_iam_are_wired(self) -> None:
        for token in (
            'contextString("ocrProvider")',
            'contextString("layoutProvider")',
            'contextString("structuredProvider")',
            'contextString("vlmProvider")',
            'contextString("captioningProvider")',
            'contextString("visualEmbeddingProvider")',
            "RAKU_OCR_PROVIDER",
            "RAKU_LAYOUT_PROVIDER",
            "RAKU_STRUCTURED_PROVIDER",
            "RAKU_VLM_PROVIDER",
            "RAKU_CAPTIONING_PROVIDER",
            "RAKU_VISUAL_EMBEDDING_PROVIDER",
            "RAKU_RUNTIME_PROFILE",
            "RAKU_CROP_STORAGE_URI",
            "ingestConnectorEnvironment",
            "RAKU_INGEST_CONNECTOR",
            "S3_BUCKET",
            "grantTextractDocumentAnalysis",
            "this.grantTextractDocumentAnalysis(answerTask.taskRole)",
            "textract:AnalyzeDocument",
            "textract:StartDocumentAnalysis",
            "textract:GetDocumentAnalysis",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)

    def test_gdrive_oauth_secrets_and_grants_are_wired(self) -> None:
        # 021-gdrive: a Google OAuth config secret (KMS-encrypted), per-tenant connector-secret grants
        # scoped to the raku/${stage}/* prefix, the durable refresh-token store env, and the output the
        # operator uses to populate credentials post-deploy.
        for token in (
            "GoogleOAuthConfigSecret",
            "/oauth/google",
            "encryptionKey: dataKey",
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GOOGLE_OAUTH_REDIRECT_URI",
            "secretsmanager:CreateSecret",
            "secret:raku/${props.stageName}/*",
            'RAKU_SECRET_STORE: "aws"',
            "AWS_SECRETS_MANAGER_KMS_KEY_ID",
            "GoogleOAuthConfigSecretName",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)
        # the durable (forward-looking) connection table migration + its down ship together
        self.assertTrue((ROOT / "infra/db/migrations/postgres/0012_data_source_oauth.sql").exists())
        self.assertTrue(
            (ROOT / "infra/db/migrations/postgres/0012_data_source_oauth.down.sql").exists()
        )

    def test_minimal_spec_profile_is_wired(self) -> None:
        # The cost-minimised tier (single Aurora instance, small Fargate tasks, Langfuse off) must be
        # selectable independently of durability (isProd governs RETAIN/backups), via --context minimalSpec.
        for token in (
            "minimalSpec",
            'tryGetContext("minimalSpec")',
            "deployLangfuse",
            "fargateSize",
            "readers: minimalSpec",
            "serverlessV2MaxCapacity: minimalSpec ? 2 : 4",
            "if (deployLangfuse)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)

    def test_migrate_seed_oneoff_task_is_wired(self) -> None:
        # A one-off in-VPC task must apply migrations + seed (Aurora is private-isolated), with the
        # outputs scripts/aws/migrate-seed.sh needs to RunTask it.
        for token in (
            "MigrateSeedTaskDefinition",
            'file: "infra/ops/Dockerfile"',
            "scripts/pg-migrate.sh up",
            "demo_seed.sh",
            "EcsClusterName",
            "MigrateSeedTaskDefinitionArn",
            "PrivateSubnetIds",
            "EcsTaskSecurityGroupId",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)
        self.assertTrue((ROOT / "infra/ops/Dockerfile").exists())
        self.assertTrue((ROOT / "scripts/aws/migrate-seed.sh").exists())

    def test_frontend_hosting_context_is_wired(self) -> None:
        for token in (
            "FrontendHostingMode",
            "frontendHosting",
            "external-vercel",
            "aws-nextjs",
            "AwsNextjsService",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack + self.bin + self.readme)

    def test_aws_nextjs_is_same_origin_real_web(self) -> None:
        # aws-nextjs must host the REAL web image and put web + API behind ONE ALB (web default,
        # API on /v1/*) so the browser is same-origin (no CORS / no mixed-content). Optional domainName
        # context adds an ACM cert + HTTPS redirect.
        for token in (
            'file: "apps/web/Dockerfile"',
            "buildArgs",
            "NEXT_PUBLIC_API_BASE",
            "ApiTargetGroup",
            '"ApiRoute"',
            '"/v1/*"',
            "RAKU_ENABLE_DEV_TOKEN_ISSUER",
            "RAKU_BASIC_AUTH_USER",
            "RAKU_BASIC_AUTH_PASSWORD",
            "WebBasicAuthSecret",
            "CognitoUserPoolClientId",
            "WebCertificate",
            "redirectHTTP",
            "allowFrom",
            'tryGetContext("domainName")',
            'tryGetContext("authMode")',
            'tryGetContext("basicAuthUser")',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)
        # The old sleep-forever placeholder must be gone.
        self.assertNotIn("sleep infinity", self.stack)

    def test_readme_documents_synth_and_resource_scope(self) -> None:
        for token in (
            "npm run build",
            "npm run synth",
            "ECS Fargate services",
            "Aurora PostgreSQL Serverless v2",
            "SQS ingestion queue plus DLQ",
            "AWS WAF WebACL",
            "CloudWatch dashboard",
            "CloudWatch alarms",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.readme)


if __name__ == "__main__":
    unittest.main()
