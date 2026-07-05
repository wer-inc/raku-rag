"""0074 — source-level contract for upload reauth loop prevention.

The file upload panel runs in the Next.js web app. These markers pin the UX invariant that an
auth-related upload failure may start one re-login recovery, but a post-login repeat failure must
stop on the page with actionable guidance instead of bouncing the user through /login forever.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FULL_SAAS = ROOT / "apps/web/app/components/FullSaasScreen.tsx"


class FileUploadReauthLoopContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = FULL_SAAS.read_text(encoding="utf-8")

    def test_reauth_attempt_state_survives_login_return(self) -> None:
        for marker in (
            "reauth_attempted?: boolean",
            "reauth_attempted: true",
            "setUploadReauthAttempted(recovery.reauth_attempted === true)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)

    def test_auto_login_is_blocked_after_reauth_attempt(self) -> None:
        self.assertIn("function uploadIssueShouldAutoLogin", self.source)
        self.assertIn("return uploadIssueNeedsLogin(issue) && !issue.reauthAttempted", self.source)
        self.assertIn("uploadIssueShouldAutoLogin(issue)", self.source)
        self.assertIn("再ログイン後もセッション確認が通りませんでした", self.source)


if __name__ == "__main__":
    unittest.main()
