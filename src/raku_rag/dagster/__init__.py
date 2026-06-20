"""Dagster-compatible control-plane shims.

The MVP test loop avoids importing Dagster itself; these modules keep request/plan shapes stable so a
real Dagster job can wrap the same service boundary later.
"""

from raku_rag.dagster.partitions import (
    DagsterPartitionKey,
    build_partition_key,
    parse_partition_key,
)
from raku_rag.dagster.run_url import dagster_run_url

__all__ = [
    "DagsterPartitionKey",
    "build_partition_key",
    "parse_partition_key",
    "dagster_run_url",
]
