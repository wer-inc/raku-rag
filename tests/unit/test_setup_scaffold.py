from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SetupScaffoldTest(unittest.TestCase):
    def test_python_lint_format_type_are_configured(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        precommit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

        self.assertIn("[tool.ruff]", pyproject)
        self.assertIn("[tool.black]", pyproject)
        self.assertIn("[tool.mypy]", pyproject)
        self.assertIn("ruff-pre-commit", precommit)
        self.assertIn("psf/black", precommit)
        self.assertIn("id: mypy", precommit)

    def test_root_compose_declares_local_dependency_stack(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        infra_compose = (ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8")
        for service in ("postgres:", "minio:", "localstack:", "langfuse:", "redis:", "dagster:"):
            with self.subTest(service=service):
                self.assertIn(service, compose)
                self.assertIn(service, infra_compose)
        self.assertIn("pgvector/pgvector:pg16", compose)
        self.assertIn("SERVICES: sqs", compose)
        self.assertIn('profiles: ["observability"]', compose)
        self.assertIn('profiles: ["dagster"]', compose)

    def test_testcontainers_fixtures_exist_for_docker_backed_tests(self) -> None:
        conftest = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
        for token in (
            "PostgresContainer",
            "LocalStackContainer",
            "DockerContainer",
            "postgres_testcontainer",
            "localstack_sqs_testcontainer",
            "minio_testcontainer",
            "redis_testcontainer",
        ):
            with self.subTest(token=token):
                self.assertIn(token, conftest)

    def test_cdk_typescript_app_scaffold_exists(self) -> None:
        package = json.loads((ROOT / "infra/cdk/package.json").read_text(encoding="utf-8"))
        for relpath in (
            "infra/cdk/cdk.json",
            "infra/cdk/tsconfig.json",
            "infra/cdk/bin/raku-rag.ts",
            "infra/cdk/lib/raku-rag-stack.ts",
        ):
            with self.subTest(path=relpath):
                self.assertTrue((ROOT / relpath).is_file())
        self.assertIn("aws-cdk-lib", package["dependencies"])
        self.assertIn("constructs", package["dependencies"])
        self.assertIn("synth", package["scripts"])


if __name__ == "__main__":
    unittest.main()
