"""P0-T02 — canonical monorepo layout invariants (ADR-016)."""
from __future__ import annotations

import json
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _p(*parts: str) -> str:
    return os.path.join(ROOT, *parts)


class TestRepoLayout(unittest.TestCase):
    def test_canonical_roots_exist(self) -> None:
        for d in [
            "apps/api", "apps/web", "workers/ingest", "packages/shared",
            "src/raku_rag", "infra/db", "infra/localstack", "docs/decisions",
            "tests/unit", "tests/contract", "tests/integration", "tests/security",
        ]:
            self.assertTrue(os.path.isdir(_p(d)), f"missing dir: {d}")

    def test_required_root_files(self) -> None:
        for f in ["package.json", "README.md", ".env.example", ".gitignore",
                  "docs/decisions/ADR-016-canonical-layout.md", "infra/docker-compose.yml"]:
            self.assertTrue(os.path.isfile(_p(f)), f"missing file: {f}")

    def test_workspace_manifest_declares_workspaces(self) -> None:
        with open(_p("package.json"), encoding="utf-8") as fh:
            pkg = json.load(fh)
        self.assertIn("apps/*", pkg.get("workspaces", []))
        self.assertIn("packages/*", pkg.get("workspaces", []))

    def test_env_example_keeps_raw_context_disabled(self) -> None:
        with open(_p(".env.example"), encoding="utf-8") as fh:
            env = fh.read()
        self.assertIn("RAKU_LOG_RAW_RETRIEVED_CONTEXT=disabled", env)  # OD-008 default


if __name__ == "__main__":
    unittest.main()
