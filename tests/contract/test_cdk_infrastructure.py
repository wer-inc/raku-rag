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
