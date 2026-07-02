"""022-ai-phone-rag — AI phone response layer over the existing RAG answer contract.

The phone layer owns call sessions, turn orchestration, scenario state, and human handoff.
It does NOT own retrieval, ACL, groundedness, or citations — those stay behind the injected
`PhoneAnswerGateway` (research.md Decision 3).
"""

from raku_rag.phone.orchestrator import PhoneCallService
from raku_rag.phone.scenarios import PhoneScenarioService, ScenarioError

__all__ = ["PhoneCallService", "PhoneScenarioService", "ScenarioError"]
