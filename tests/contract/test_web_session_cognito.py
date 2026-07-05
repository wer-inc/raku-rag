"""0074 — source-level contract for browser Cognito session recovery.

apps/web currently relies on Next/TypeScript build checks rather than a dedicated TS unit runner.
These markers pin the security-relevant browser boundary: stale or mismatched Cognito tokens must
not be sent silently, and missing tenant configuration must become a typed recovery code.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "apps/web/lib/session.ts"


class WebSessionCognitoContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SESSION.read_text(encoding="utf-8")

    def test_app_session_error_codes_are_typed(self) -> None:
        for marker in (
            "export type AppSessionErrorCode",
            '"reauth_required"',
            '"session_mismatch"',
            '"tenant_not_configured"',
            '"session_missing"',
            "export class AppSessionError extends Error",
            "isAppSessionError",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)

    def test_stored_cognito_token_validation_checks_current_auth_config(self) -> None:
        for marker in (
            "validateCognitoTokenForApp",
            "normalizedIssuer(config.cognito_issuer)",
            "tokenClientMatches(claims, config.cognito_client_id)",
            'claimString(claims, "custom:tenant_id")',
            "loadStoredAppCognitoToken(config)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)

    def test_id_token_is_preferred_and_access_token_requires_tenant(self) -> None:
        self.assertLess(
            self.source.find("COGNITO_ID_TOKEN_KEY"),
            self.source.find("COGNITO_ACCESS_TOKEN_KEY"),
            "App API token selection must prefer ID token before access token",
        )
        self.assertIn('{ key: COGNITO_ID_TOKEN_KEY, kind: "id" }', self.source)
        self.assertIn('{ key: COGNITO_ACCESS_TOKEN_KEY, kind: "access" }', self.source)
        self.assertIn("if (!cognitoTenantFromClaims(claims))", self.source)

    def test_unrecoverable_cognito_session_is_cleared_before_typed_error(self) -> None:
        self.assertIn("const refreshed = await refreshCognitoSession(config)", self.source)
        self.assertIn(
            "clearSessionToken();\n  throw new AppSessionError(stored.code);", self.source
        )


if __name__ == "__main__":
    unittest.main()
