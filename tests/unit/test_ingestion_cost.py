"""ADR-018 §18.3 — the config-driven provider cost model."""

from __future__ import annotations

import os
import unittest
from contextlib import contextmanager

from raku_rag.services.ingestion_cost import COST_MODEL_ENV, provider_cost_model


@contextmanager
def _env(value: str | None):
    saved = os.environ.get(COST_MODEL_ENV)
    if value is None:
        os.environ.pop(COST_MODEL_ENV, None)
    else:
        os.environ[COST_MODEL_ENV] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(COST_MODEL_ENV, None)
        else:
            os.environ[COST_MODEL_ENV] = saved


class ProviderCostModelTest(unittest.TestCase):
    def test_default_is_empty_not_invented(self) -> None:
        with _env(None):
            self.assertEqual(provider_cost_model(), {})

    def test_parses_json_map_of_floats(self) -> None:
        with _env('{"google_docai": 0.0015, "rapidocr": 0}'):
            model = provider_cost_model()
        self.assertAlmostEqual(model["google_docai"], 0.0015)
        self.assertEqual(model["rapidocr"], 0.0)

    def test_garbage_falls_back_to_empty(self) -> None:
        for bad in ("not json", "[1,2,3]", ""):
            with _env(bad):
                self.assertEqual(provider_cost_model(), {})

    def test_non_numeric_entries_are_skipped(self) -> None:
        with _env('{"a": "x", "b": 0.01}'):
            self.assertEqual(provider_cost_model(), {"b": 0.01})


if __name__ == "__main__":
    unittest.main()
