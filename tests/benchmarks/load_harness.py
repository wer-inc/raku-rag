"""T117 — load-test harness: drive a request path under concurrency and report p50/p95/p99.

Reusable against any callable (the in-memory MvpSystem answer/search path for the sandbox smoke, or a
thin HTTP client against the deployed service for real load numbers). Stdlib only (ThreadPoolExecutor).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((len(ordered) - 1) * p)))
    return ordered[idx]


@dataclass(frozen=True)
class LoadStats:
    count: int
    errors: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    qps: float

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "errors": self.errors,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "qps": self.qps,
        }


def run_load(call: Callable[[int], None], *, concurrency: int, iterations: int) -> LoadStats:
    """Run ``call(i)`` ``iterations`` times across ``concurrency`` workers, timing each call.

    ``call`` performs one request and raises on failure (an isolation/contract violation should raise
    so it is counted as an error). Returns latency percentiles + achieved QPS.
    """
    latencies: list[float] = []
    errors = 0

    def _one(i: int) -> float:
        start = time.perf_counter()
        call(i)
        return (time.perf_counter() - start) * 1000.0

    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(_one, i) for i in range(iterations)]
        for future in futures:
            try:
                latencies.append(future.result())
            except Exception:
                errors += 1
    wall = time.perf_counter() - wall_started
    return LoadStats(
        count=len(latencies),
        errors=errors,
        p50_ms=percentile(latencies, 0.50),
        p95_ms=percentile(latencies, 0.95),
        p99_ms=percentile(latencies, 0.99),
        qps=(len(latencies) / wall) if wall > 0 else 0.0,
    )


__all__ = ["LoadStats", "percentile", "run_load"]
