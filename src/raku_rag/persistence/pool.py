"""P3-2 — a minimal stdlib Postgres connection pool (no psycopg_pool dependency; Track-A friendly).

A bounded pool hands out one connection per acquiring thread so a threaded/scaled deployment can run
concurrent requests SAFELY: each request gets its OWN connection and sets its OWN tenant GUC. That
per-connection isolation is REQUIRED for RLS tenant isolation under concurrency — sharing a single
connection's ``app.current_tenant_id`` across threads would race and leak across tenants. The
single-threaded answer-service uses one connection today (correct for its model); this is the building
block for the threaded/horizontally-scaled deployment.
"""

from __future__ import annotations

import contextlib
import queue
from typing import Callable, Iterator


class PostgresConnectionPool:
    def __init__(self, dsn: str, *, size: int = 8, connect: Callable[[str], object] | None = None):
        self._size = max(1, int(size))
        self._connect = connect or self._default_connect
        self._pool: queue.Queue = queue.Queue(maxsize=self._size)
        for _ in range(self._size):
            self._pool.put(self._connect(dsn))

    @staticmethod
    def _default_connect(dsn: str) -> object:
        import psycopg

        return psycopg.connect(dsn, autocommit=True)

    @contextlib.contextmanager
    def acquire(self, *, timeout: float = 10.0) -> Iterator[object]:
        conn = self._pool.get(timeout=timeout)
        try:
            yield conn
        finally:
            self._pool.put(conn)

    def size(self) -> int:
        return self._size

    def available(self) -> int:
        return self._pool.qsize()

    def close(self) -> None:
        while not self._pool.empty():
            try:
                self._pool.get_nowait().close()  # type: ignore[attr-defined]
            except Exception:
                pass


__all__ = ["PostgresConnectionPool"]
