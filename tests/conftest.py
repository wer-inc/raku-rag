"""Optional pytest/testcontainers fixtures for Docker-backed integration tests.

The stdlib unittest gate does not import this file; pytest users can opt into these fixtures when
running local or CI tests with Docker available.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def postgres_testcontainer() -> Iterator[dict[str, str]]:
    module = pytest.importorskip("testcontainers.postgres")
    with module.PostgresContainer("pgvector/pgvector:pg16") as postgres:
        yield {
            "POSTGRES_URL": postgres.get_connection_url(),
            "POSTGRES_HOST": postgres.get_container_host_ip(),
            "POSTGRES_PORT": postgres.get_exposed_port(5432),
        }


@pytest.fixture(scope="session")
def localstack_sqs_testcontainer() -> Iterator[dict[str, str]]:
    module = pytest.importorskip("testcontainers.localstack")
    with module.LocalStackContainer("localstack/localstack:3").with_services("sqs") as localstack:
        endpoint = localstack.get_url()
        yield {
            "SQS_ENDPOINT": endpoint,
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
        }


@pytest.fixture(scope="session")
def minio_testcontainer() -> Iterator[dict[str, str]]:
    module = pytest.importorskip("testcontainers.core.container")
    container = (
        module.DockerContainer("minio/minio:latest")
        .with_command('server /data --console-address ":9001"')
        .with_env("MINIO_ROOT_USER", "minioadmin")
        .with_env("MINIO_ROOT_PASSWORD", "minioadmin")
        .with_exposed_ports(9000, 9001)
    )
    with container:
        yield {
            "S3_ENDPOINT": f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9000)}",
            "S3_ACCESS_KEY": "minioadmin",
            "S3_SECRET_KEY": "minioadmin",
            "S3_BUCKET": "raku-test",
        }


@pytest.fixture(scope="session")
def redis_testcontainer() -> Iterator[dict[str, str]]:
    module = pytest.importorskip("testcontainers.core.container")
    container = module.DockerContainer("redis:7-alpine").with_exposed_ports(6379)
    with container:
        yield {
            "REDIS_URL": f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"
        }
