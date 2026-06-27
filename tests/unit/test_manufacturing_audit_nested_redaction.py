from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import AuditLogEntry, InMemoryAuditLogWriter


def _claims() -> IdentityClaims:
    return IdentityClaims(tenant_id="t1", user_id="u1")


class ManufacturingAuditNestedRedactionTest(unittest.TestCase):
    def test_nested_client_metadata_is_redacted(self) -> None:
        writer = InMemoryAuditLogWriter()
        writer.record(
            AuditLogEntry(
                tenant_id="t1",
                log_id="log-1",
                timestamp="2026-06-27T00:00:00Z",
                action="answer.safety_evaluated",
                client_metadata={
                    "visual_evidence": [
                        {
                            "verifiers": [
                                {
                                    "verifier_id": "v1",
                                    "reason_code": "contact alice@example.com",
                                }
                            ]
                        }
                    ]
                },
            )
        )

        stored = writer.read_all(_claims())[0]
        reason = stored.client_metadata["visual_evidence"][0]["verifiers"][0]["reason_code"]
        self.assertNotIn("alice@example.com", reason)
        self.assertIn("[REDACTED:email]", reason)


if __name__ == "__main__":
    unittest.main()
