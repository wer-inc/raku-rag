from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SearchAnswerContractTest(unittest.TestCase):
    def test_search_and_answer_facade_contracts_are_published(self) -> None:
        openapi = (ROOT / "apps/api/src/openapi/openapi.controller.ts").read_text()
        app_module = (ROOT / "apps/api/src/app.module.ts").read_text()
        answer_controller = (ROOT / "apps/api/src/answer/answer.controller.ts").read_text()
        search_controller = (ROOT / "apps/api/src/search/search.controller.ts").read_text()
        assets_controller = (ROOT / "apps/api/src/assets/assets.controller.ts").read_text()

        for expected in (
            '"/answer"',
            '"/search"',
            '"/assets/{asset_id}"',
            "#/components/schemas/AnswerRequest",
            "#/components/schemas/AnswerResponse",
            "#/components/schemas/SearchRequest",
            "#/components/schemas/SearchResponse",
            "#/components/schemas/VisualAssetResponse",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, openapi)

        self.assertIn("AnswerController", app_module)
        self.assertIn("SearchController", app_module)
        self.assertIn("AssetsController", app_module)
        self.assertIn("AuthMiddleware", app_module)

        self.assertIn("body?.query", answer_controller)
        self.assertIn("body?.query", search_controller)
        self.assertIn("tenant_id: p.tenant_id", answer_controller)
        self.assertIn("tenant_id: p.tenant_id", search_controller)
        # In the manufacturing product, legacy /v1/answer must still use the safety overlay.
        self.assertIn("/internal/manufacturing/answer", answer_controller)
        self.assertNotIn("`${base}/internal/answer`", answer_controller)
        self.assertIn("/internal/search", search_controller)
        self.assertIn("/internal/assets", assets_controller)
        self.assertIn("x-raku-tenant-id", assets_controller)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
