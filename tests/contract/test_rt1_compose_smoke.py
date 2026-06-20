from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Rt1ComposeSmokeContract(unittest.TestCase):
    def setUp(self) -> None:
        self.script = (ROOT / "scripts" / "docker-compose-smoke.sh").read_text(encoding="utf-8")

    def test_smoke_boots_every_required_local_dependency(self) -> None:
        self.assertIn("up -d --wait postgres minio localstack trace-sink", self.script)
        for service in ("postgres", "minio", "localstack", "trace-sink"):
            with self.subTest(service=service):
                self.assertIn(service, self.script)

    def test_smoke_verifies_required_dependency_health(self) -> None:
        for required in (
            "SELECT 1 FROM pg_extension WHERE extname='vector';",
            "awslocal sqs list-queues",
            "raku-ingest",
            "mc ready local",
            "TRACE_SINK_HEALTH_URL",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.script)

    def test_environment_limitations_are_distinguished_from_stack_failures(self) -> None:
        for required in (
            "Docker is not installed or not on PATH.",
            "Docker daemon is not reachable.",
            "Docker Compose v2 is required.",
            "unshare -m true",
            "exit 2",
            "exit 1",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.script)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
