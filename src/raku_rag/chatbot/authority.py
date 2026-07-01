"""Per-tenant ChatBot authority-level config (P0 seam).

`chatbot_authority_level` selects which registered `AnswerEngine` rung answers a tenant's free-text
turns (see the authority ladder in
docs/production-readiness/chatbot-conversational-agent-roadmap.md). Only "L0" has an implementation
today; `ChatbotService` falls back to L0 for any level it doesn't recognize, so this repository is
safe to wire in before any other rung exists — flipping a tenant's level only takes effect once a
later phase registers the corresponding engine.

P0 keeps this in-memory (constructor-injectable, mirroring `ChatbotSourcePolicyRepository`) rather
than adding a Postgres table + migration: no engine besides L0 exists yet, so there is nothing for a
persisted value to change, and every tenant must default to L0 regardless of storage. A
`PostgresChatbotAuthorityRepository` (mirroring `PostgresChatbotSourcePolicyRepository` /
`infra/db/migrations/postgres/0016_chatbot_source_exposure_policies.sql`) is the natural addition
once P1 ships a real second rung and needs the dial to survive process restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_CHATBOT_AUTHORITY_LEVEL = "L0"


class ChatbotAuthorityRepository(Protocol):
    def get(self, tenant_id: str) -> str: ...

    def set(self, tenant_id: str, level: str) -> str: ...


@dataclass
class InMemoryChatbotAuthorityRepository:
    _levels: dict[str, str] = field(default_factory=dict)

    def get(self, tenant_id: str) -> str:
        return self._levels.get(tenant_id, DEFAULT_CHATBOT_AUTHORITY_LEVEL)

    def set(self, tenant_id: str, level: str) -> str:
        self._levels[tenant_id] = level
        return level
