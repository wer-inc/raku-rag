"""Dagster run URL helper."""

from __future__ import annotations

from urllib.parse import quote


def dagster_run_url(base_url: str, run_id: str) -> str:
    if not base_url:
        raise ValueError("base_url is required")
    if not run_id:
        raise ValueError("run_id is required")
    return f"{base_url.rstrip('/')}/runs/{quote(run_id, safe='')}"
