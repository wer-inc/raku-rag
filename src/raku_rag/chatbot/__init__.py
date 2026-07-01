"""Conversation ChatBot layer that composes the existing RAG answer service."""

from raku_rag.chatbot.answer_engine import (
    AnswerEngine,
    DialogueContext,
    L0DeterministicAnswerEngine,
)
from raku_rag.chatbot.authority import (
    DEFAULT_CHATBOT_AUTHORITY_LEVEL,
    ChatbotAuthorityRepository,
    InMemoryChatbotAuthorityRepository,
)
from raku_rag.chatbot.dialogue_manager import DialogueManager
from raku_rag.chatbot.service import ChatbotService

__all__ = [
    "ChatbotService",
    "AnswerEngine",
    "DialogueContext",
    "L0DeterministicAnswerEngine",
    "DialogueManager",
    "ChatbotAuthorityRepository",
    "InMemoryChatbotAuthorityRepository",
    "DEFAULT_CHATBOT_AUTHORITY_LEVEL",
]
