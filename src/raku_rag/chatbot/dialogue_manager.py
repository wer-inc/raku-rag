"""DialogueManager: reads/derives conversation thread state from a ChatSession.

This is the conversation-management layer split out from RAG answering (P0 of
docs/production-readiness/chatbot-conversational-agent-roadmap.md). It owns reconstructing "what was
the last grounded answer, and what did it cite" from `ChatSession.messages` — the thread state
(topic/last citations/active source scope) that an `AnswerEngine` needs. It has no opinion on
quick-reply syntax, intent routing, or ACL/source-policy; those stay in `ChatbotService`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

from raku_rag.chatbot.answer_engine import DialogueContext

if TYPE_CHECKING:
    from raku_rag.chatbot.service import ChatSession


class DialogueManager:
    def last_answer_context(
        self, session: "ChatSession", is_quick_reply_value: Callable[[str], object]
    ) -> dict | None:
        answer_index = -1
        answer_message = None
        for index in range(len(session.messages) - 1, -1, -1):
            message = session.messages[index]
            if (
                message.role == "assistant"
                and message.ai_action == "answer_with_citations"
                and message.citations
            ):
                answer_index = index
                answer_message = message
                break
        if answer_message is None:
            return None

        metadata = dict(answer_message.metadata or {})
        previous_question = ""
        for message in reversed(session.messages[:answer_index]):
            if message.role == "user" and not is_quick_reply_value(message.content_redacted):
                previous_question = message.content_redacted
                break
        if not previous_question:
            previous_question = str(metadata.get("source_question") or "")

        document_ids = [
            str(citation.get("document_id") or "")
            for citation in answer_message.citations
            if citation.get("document_id")
        ]
        return {
            "question": previous_question,
            "answer": answer_message.content_redacted,
            "source_answer_text": str(
                metadata.get("source_answer_text") or answer_message.content_redacted
            ),
            "source_question": str(metadata.get("source_question") or previous_question),
            "citations": [dict(citation) for citation in answer_message.citations],
            "document_ids": list(dict.fromkeys(document_ids)),
        }

    def build_context(
        self,
        session: "ChatSession",
        is_quick_reply_value: Callable[[str], object],
        collection_id: str | None,
        source_policy_ids: Sequence[str] = (),
    ) -> DialogueContext:
        context = self.last_answer_context(session, is_quick_reply_value) or {}
        return DialogueContext(
            collection_id=collection_id,
            previous_question=context.get("question") or None,
            previous_answer=context.get("answer") or None,
            previous_citations=tuple(dict(c) for c in context.get("citations") or ()),
            previous_document_ids=tuple(context.get("document_ids") or ()),
            source_policy_ids=tuple(source_policy_ids),
        )
