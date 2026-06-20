from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class FrontendResidencyFallbackContractTest(unittest.TestCase):
    def test_frontend_hosting_residency_fallback_is_documented(self) -> None:
        infra_readme = (ROOT / "infra/cdk/README.md").read_text(encoding="utf-8")
        web_readme = (ROOT / "apps/web/README.md").read_text(encoding="utf-8")
        combined = infra_readme + "\n" + web_readme

        for token in (
            "Vercel AI SDK",
            "AWS-hosted Next.js",
            "aws-nextjs",
            "frontendHosting=external-vercel",
            "frontendHosting=aws-nextjs",
            "ProviderPolicy",
            "raw retrieved context",
            "tenant residency profile",
        ):
            with self.subTest(token=token):
                self.assertIn(token, combined)

        self.assertIn("ECS Fargate", combined)
        self.assertIn("CloudWatch", combined)


if __name__ == "__main__":
    unittest.main()
