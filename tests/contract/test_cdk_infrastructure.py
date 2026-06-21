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
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.stack)

    def test_worker_service_is_long_running_and_has_dlq_projection(self) -> None:
        for token in (
            'command: ["python", "-m", "workers.ingest.worker", "--serve"]',
            "SQS_QUEUE_URL",
            "SQS_DLQ_URL",
            "deadLetterQueue.queueUrl",
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
            "CloudWatch dashboard",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.readme)


if __name__ == "__main__":
    unittest.main()
