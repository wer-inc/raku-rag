"""P0-T21 — deterministic local test fixtures (parser / ACL / eval / industry).

Image / scanned-PDF parser fixtures are intentionally deferred to the visual-RAG phase (US6),
consistent with the Phase 0/1 out-of-scope list.
"""

from __future__ import annotations

import json
import os

FIXTURES_DIR = os.path.dirname(__file__)


def fixture_path(*parts: str) -> str:
    return os.path.join(FIXTURES_DIR, *parts)


def load_text(*parts: str) -> str:
    with open(fixture_path(*parts), encoding="utf-8") as fh:
        return fh.read()


def load_json(*parts: str):
    with open(fixture_path(*parts), encoding="utf-8") as fh:
        return json.load(fh)


#: parser fixtures present in Phase 0 (image/scanned-PDF deferred to US6)
PARSER_FIXTURES = ("sample.txt", "sample.md", "sample.html", "sample.csv", "sample_ja.txt")
