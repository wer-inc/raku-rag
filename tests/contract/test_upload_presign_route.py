"""0047/0045 — contract pins on the presign route SOURCE (apps/web has no TS test runner).

The web workspace ships the Next.js route handler that (a) signs the x-amz-meta-* headers into the
presigned PUT (issue 0047: unsigned metadata made S3 return HeadersNotSigned/403), (b) scopes keys
to the tenant prefix (issue 0044), and (c) registers the provenance record BEFORE returning the URL
(issue 0045, fail-closed). These invariants are cheap to regress silently — pin them as source
markers, same style as the SQL text locks in tests/contract/test_schema_lock_migration_sql.py.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTE = ROOT / "apps/web/app/api/upload/presign/route.ts"


class UploadPresignRouteContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ROUTE.read_text(encoding="utf-8")

    def test_metadata_headers_are_signed_and_unhoistable(self) -> None:
        # 0047: every header the browser must send has to be part of the SigV4 signature, and the
        # x-amz-meta-* set must stay header-borne (not hoisted into the query string).
        self.assertIn("signableHeaders: new Set(Object.keys(uploadHeaders))", self.source)
        self.assertIn("unhoistableHeaders: new Set(Object.keys(metadataHeaders))", self.source)
        for marker in (
            '"x-amz-meta-raku-tenant-id"',
            '"x-amz-meta-raku-user-id"',
            '"x-amz-meta-raku-upload-id"',
        ):
            self.assertIn(marker, self.source)
        # The signed header set must include content-type + the metadata headers.
        self.assertIn('"content-type": contentType, ...metadataHeaders', self.source)

    def test_object_keys_are_tenant_prefixed(self) -> None:
        # 0044: key = tenants/<tenant>/uploads/<day>/<uuid><ext>
        self.assertRegex(
            self.source,
            re.compile(r"`tenants/\$\{tenantSegment\}/uploads/\$\{day\}/\$\{uploadId\}"),
        )

    def test_provenance_registration_happens_before_presigning(self) -> None:
        # 0045: the record registration (fail-closed) must precede getSignedUrl in the handler.
        register_at = self.source.find("/v1/uploads")
        presign_at = self.source.find("getSignedUrl(client, command")
        self.assertGreater(register_at, 0, "presign route must register the upload record")
        self.assertGreater(presign_at, register_at, "registration must precede URL signing")
        self.assertIn("アップロード準備に失敗しました", self.source)

    def test_session_is_verified_before_any_presign_work(self) -> None:
        # Cognito/dev session validation (via /v1/whoami) gates the route; principal-derived
        # tenant — never a body field — feeds the key prefix.
        self.assertIn("assertAppSession(req)", self.source)
        self.assertIn("session.principal.tenant_id", self.source)
        self.assertNotIn("body.tenant_id", self.source)

    def test_auth_failures_return_client_safe_error_codes(self) -> None:
        # 0074: the browser must not surface raw "Cognito session is invalid" during file upload.
        for code in (
            "session_missing",
            "reauth_required",
            "session_mismatch",
            "tenant_not_configured",
            "permission_denied",
        ):
            with self.subTest(code=code):
                self.assertIn(code, self.source)
        self.assertIn("error_code", self.source)
        self.assertIn("classifyBearerToken(authorization)", self.source)
        self.assertIn('claimString(claims, "custom:tenant_id")', self.source)
        self.assertNotIn("Cognito session is invalid", self.source)

    def test_session_verify_origin_forces_https_behind_cloudfront(self) -> None:
        # 0077: behind CloudFront the ALB hop is http, so a self-fetch to the reconstructed http
        # origin hits redirect-to-https and fetch() drops Authorization -> whoami 401 -> upload
        # wrongly reported as session_mismatch. The verify origin must be https for the public edge
        # (only direct ALB DNS / localhost keep plain http), and must honor an internal override.
        for marker in (
            "function directHttpHost",
            '.endsWith(".elb.amazonaws.com")',
            "directHttpHost(host) ? forwardedProto : \"https\"",
            "RAKU_UPLOAD_VERIFY_ORIGIN",
            "RAKU_INTERNAL_API_ORIGIN",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)

    def test_valid_looking_token_rejected_by_whoami_is_session_mismatch(self) -> None:
        # If /v1/whoami rejects a JWT whose local claims are current and tenant-scoped, another
        # login is unlikely to fix the server-side Cognito/API boundary. Do not label it as a
        # recoverable reauth loop.
        tenant_check = 'if (!claimString(claims, "custom:tenant_id")) return "tenant_not_configured";'
        mismatch_fallback = 'return "session_mismatch";'
        self.assertIn(tenant_check, self.source)
        self.assertGreater(
            self.source.find(mismatch_fallback, self.source.find(tenant_check)),
            self.source.find(tenant_check),
        )


if __name__ == "__main__":
    unittest.main()
