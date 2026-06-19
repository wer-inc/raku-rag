"""T010 — TokenVerifier: validate the calling app's signed user token → IdentityClaims (FR-025).

MVP uses an HMAC-SHA256 signed compact token. Production swaps in JWT/JWKS behind this class.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from raku_rag.core.errors import AuthError
from raku_rag.domain.models import IdentityClaims


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_token(claims: IdentityClaims, secret: str) -> str:
    """Helper to mint a signed token (used by calling apps / tests)."""
    payload = {
        "tenant_id": claims.tenant_id,
        "user_id": claims.user_id,
        "groups": list(claims.groups),
        "roles": list(claims.roles),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


class TokenVerifier:
    def __init__(self, secret: str) -> None:
        self._secret = secret

    def verify(self, token: str, *, expected_tenant_id: str) -> IdentityClaims:
        """Verify signature and enforce tenant binding.

        ``expected_tenant_id`` is the tenant of the authenticated API client. A token whose
        claims name a different tenant is rejected (FR-025 / tenant isolation).
        """
        try:
            body, sig = token.split(".", 1)
            expected_sig = _b64(
                hmac.new(self._secret.encode(), body.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(sig, expected_sig):
                raise AuthError("invalid token signature")
            payload = json.loads(_unb64(body))
        except AuthError:
            raise
        except Exception as exc:  # malformed token
            raise AuthError("malformed token") from exc

        claims = IdentityClaims(
            tenant_id=payload["tenant_id"],
            user_id=payload["user_id"],
            groups=tuple(payload.get("groups", ())),
            roles=tuple(payload.get("roles", ())),
        )
        if claims.tenant_id != expected_tenant_id:
            # Do not leak which tenant the token belongs to.
            raise AuthError("token tenant mismatch")
        return claims
