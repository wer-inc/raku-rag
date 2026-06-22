"""Stable presentation template for grounded answers.

This is an API/display contract, not a grounding mechanism. It keeps clients from inventing their own
ad hoc answer sections while preserving the raw `text`, citations, and status fields.
"""

from __future__ import annotations

ANSWER_TEMPLATE_VERSION = "grounded-answer-display-v1"


def answer_display_sections(answer) -> tuple[dict, ...]:
    sections: list[dict] = [
        {
            "id": "status",
            "title": "Status",
            "text": str(getattr(answer, "status", "") or ""),
        }
    ]
    text = getattr(answer, "text", None)
    if text:
        sections.append({"id": "answer", "title": "Answer", "text": str(text)})

    safety = _safety_section(answer)
    if safety is not None:
        sections.append(safety)

    citations = tuple(getattr(answer, "citations", ()) or ())
    if citations:
        sections.append(
            {
                "id": "evidence",
                "title": "Evidence",
                "items": [
                    {
                        "document_id": str(getattr(citation, "document_id", "") or ""),
                        "chunk_id": str(getattr(citation, "chunk_id", "") or ""),
                        "source_id": str(getattr(citation, "source_id", "") or ""),
                    }
                    for citation in citations
                ],
            }
        )
    return tuple(sections)


def answer_format_metadata(answer) -> dict:
    return {
        "answer_template_version": ANSWER_TEMPLATE_VERSION,
        "display_sections": list(answer_display_sections(answer)),
    }


def _safety_section(answer) -> dict | None:
    fields = {
        "high_risk": bool(getattr(answer, "high_risk", False)),
        "safety_block_reason": str(getattr(answer, "safety_block_reason", "") or ""),
        "obsolete_warning": bool(getattr(answer, "obsolete_warning", False)),
        "requires_onsite_confirmation": bool(
            getattr(answer, "requires_onsite_confirmation", False)
        ),
        "notice": str(getattr(answer, "notice", "") or ""),
    }
    if not any(value for value in fields.values()):
        return None
    return {
        "id": "safety",
        "title": "Safety",
        "fields": fields,
    }
