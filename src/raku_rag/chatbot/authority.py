"""Per-tenant ChatBot authority-level config (P0 seam).

`chatbot_authority_level` selects which registered `AnswerEngine` rung answers a tenant's free-text
turns (see the authority ladder in
docs/production-readiness/chatbot-conversational-agent-roadmap.md). "L0" through "L4" all have
implementations today (P1-P5); `ChatbotService` falls back to L0 for any level it doesn't recognize
(e.g. "L5"), so this repository stays safe to wire a tenant to a level before that level's engine
exists — flipping a tenant's level only takes effect once the corresponding engine is registered, and
some registered engines (notably "L4" as of P5) are themselves inert no-ops until a further,
deliberately-unwired dependency (see chatbot/agent.py) is also supplied.

P0 keeps this in-memory (constructor-injectable, mirroring `ChatbotSourcePolicyRepository`) rather
than adding a Postgres table + migration: every tenant must default to L0 regardless of storage, and
no phase through P5 has yet needed the dial to survive process restarts (only the in-memory demo-
tenant flags in `ChatbotService.__init__`/`apps/answer-service/server.py` are used today). A
`PostgresChatbotAuthorityRepository` (mirroring `PostgresChatbotSourcePolicyRepository` /
`infra/db/migrations/postgres/0016_chatbot_source_exposure_policies.sql`) is the natural addition once
a real pilot tenant needs the dial to survive process restarts.
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
