"""P0-T15 — local stack boot smoke (RT1/RT3). Skips cleanly when Docker is unavailable so the test
suite stays green on machines without Docker; on a Docker host it asserts the core services boot and
pgvector is available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from urllib.request import urlopen

COMPOSE = os.path.join(os.path.dirname(__file__), "..", "..", "infra", "docker-compose.yml")


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


@unittest.skipUnless(_docker_available(), "Docker not available (compose boot is host-only)")
class TestStackBoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                COMPOSE,
                "up",
                "-d",
                "--wait",
                "postgres",
                "minio",
                "localstack",
                "trace-sink",
            ],
            check=True,
            timeout=300,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        subprocess.run(["docker", "compose", "-f", COMPOSE, "down", "-v"], timeout=120)

    def test_pgvector_extension_available(self) -> None:
        out = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                COMPOSE,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "raku",
                "-d",
                "raku",
                "-tAc",
                "SELECT 1 FROM pg_extension WHERE extname='vector'",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(out.stdout.strip(), "1")

    def test_localstack_sqs_queue_available(self) -> None:
        out = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                COMPOSE,
                "exec",
                "-T",
                "localstack",
                "awslocal",
                "sqs",
                "list-queues",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertIn("raku-ingest", out.stdout)

    def test_minio_ready(self) -> None:
        out = subprocess.run(
            ["docker", "compose", "-f", COMPOSE, "exec", "-T", "minio", "mc", "ready", "local"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_trace_sink_health(self) -> None:
        with urlopen("http://127.0.0.1:13133/", timeout=10) as response:
            self.assertLess(response.status, 400)


if __name__ == "__main__":
    unittest.main()
