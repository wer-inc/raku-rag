"""0075 — source-level contract for common web auth recovery.

The web app does not have a dedicated TS unit runner today, so this pins the shared auth recovery
boundary at source level: API error_code must survive the client, and common screen loaders must not
send users through an endless /login loop when re-login cannot fix the API-side Cognito failure.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_CLIENT = ROOT / "apps/web/lib/api-client.ts"
FULL_SAAS = ROOT / "apps/web/app/components/FullSaasScreen.tsx"
LOGIN_PAGE = ROOT / "apps/web/app/login/page.tsx"


class WebAuthRecoveryContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.api_client = API_CLIENT.read_text(encoding="utf-8")
        cls.full_saas = FULL_SAAS.read_text(encoding="utf-8")
        cls.login_page = LOGIN_PAGE.read_text(encoding="utf-8")

    def test_api_client_preserves_error_code_and_status(self) -> None:
        for marker in (
            "export class ApiClientError extends Error",
            "status: number",
            "errorCode?: string",
            'bodyString(body, "error_code")',
            "throw new ApiClientError",
            "export function isApiClientError",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.api_client)

    def test_common_loader_uses_one_shot_reauth_guard(self) -> None:
        for marker in (
            'const AUTH_RECOVERY_KEY = "raku.authRecovery"',
            "function startLoginRecoveryForAuthError",
            "authRecoveryAttempted(returnTo)",
            "saveAuthRecoveryState(returnTo)",
            "clearAuthRecoveryState();",
            'new URLSearchParams({ reauth: "1", return_to:',
            "formatLoadError(err, { reauthAttempted })",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.full_saas)

    def test_non_recoverable_auth_codes_do_not_auto_redirect(self) -> None:
        for marker in (
            'code === "session_mismatch"',
            'code === "tenant_not_configured"',
            'code === "permission_denied"',
            "return false;",
            "再ログイン後もセッション確認が通りませんでした",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.full_saas)
        self.assertNotIn("redirectToLoginAfterAuthError", self.full_saas)

    def test_return_to_login_forces_fresh_credentials(self) -> None:
        for marker in (
            "function isReauthRequest",
            'params.get("reauth") === "1" || params.has("return_to")',
            "if (reauth) clearSessionToken();",
            "if (!reauth && session.isCognito && session.isAuthenticated)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.login_page)

    def test_file_browser_loader_uses_auth_recovery(self) -> None:
        for marker in (
            "async function reloadFiles",
            "startLoginRecoveryForAuthError(err)",
            "setLoadError(formatLoadError(err, { reauthAttempted }))",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.full_saas)


if __name__ == "__main__":
    unittest.main()
