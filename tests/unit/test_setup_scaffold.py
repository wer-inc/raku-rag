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

    def test_root_and_infra_compose_stay_in_sync(self) -> None:
        # The root docker-compose.yml header says "Keep infra/docker-compose.yml in sync." Mechanize
        # that drift-prevention: the two intentional copies (root for `docker compose up`, infra/ for
        # scripts + RT1 per ADR-016) MUST declare the SAME service set and the SAME image per service,
        # so a service/image added to one but not the other fails here instead of silently drifting.
        def _services(text: str) -> dict:
            services: dict = {}
            in_services = False
            current = None
            for line in text.splitlines():
                if line.strip().startswith("#"):
                    continue
                if line.rstrip() == "services:":
                    in_services = True
                    continue
                if in_services and line and not line[0].isspace():
                    break  # left the services: block
                if not in_services:
                    continue
                if line[:2] == "  " and line[2:3] != " " and line.rstrip().endswith(":"):
                    current = line.strip().rstrip(":")
                    services[current] = None
                elif current is not None and line.strip().startswith("image:"):
                    services[current] = line.strip().split("image:", 1)[1].strip()
            return services

        root = _services((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        infra = _services((ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8"))
        self.assertEqual(
            set(root),
            set(infra),
            "root and infra docker-compose.yml declare different services (they must stay in sync)",
        )
        for svc in root:
            self.assertEqual(
                root[svc],
                infra[svc],
                f"service {svc!r} has a different image between root and infra compose (drift)",
            )

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
