"""Deterministic DraftArtifact -> markdown renderer for the publish path (issue 0019).

When a reviewer-approved draft is PUBLISHED back into the knowledge base, its structured
``content`` (built by drafts/generator.py) must become a plain-text 001 Document body. This module
renders that body deterministically (pure function of the artifact — no clock, no randomness) so a
re-render of the same artifact is byte-identical and the published document is reproducible from
the audited draft.

Safe-side rendering (FR-MFG-010b/011 carried through publish): item markers survive verbatim —
an item the generator held back as unconfirmed (``status=needs_review``) is rendered with an
explicit 未確定 marker, never silently promoted to asserted fact by publication. What was approved
is exactly what is published.

stdlib only.
"""

from __future__ import annotations

from raku_rag.manufacturing.domain.draft import DraftArtifact, DraftType

# Human titles for the five draft kinds (mirrors the web DRAFT_KINDS labels).
_KIND_TITLES: dict[DraftType, str] = {
    DraftType.CHECKLIST: "点検チェックリスト",
    DraftType.TROUBLE_REPORT: "トラブル報告",
    DraftType.QUALITY_REPORT: "品質報告",
    DraftType.TRAINING: "教育資料",
    DraftType.FAQ: "FAQ",
}

# Marker prefixed to an item the generator flagged as NOT backed by approved+effective evidence.
_UNCONFIRMED_MARKER = "【未確定・要確認】"


def _item_line(item: object) -> str:
    """Render one ``content.items`` entry as a single markdown list line (marker-preserving)."""
    if isinstance(item, str):
        return f"- {item}"
    if isinstance(item, dict):
        text = str(item.get("text") or "")
        confirmed = bool(item.get("confirmed"))
        unconfirmed = (not confirmed) or str(item.get("status") or "") == "needs_review"
        prefix = f"{_UNCONFIRMED_MARKER} " if unconfirmed else ""
        return f"- {prefix}{text}".rstrip()
    return f"- {item!r}"


def render_draft_markdown(artifact: DraftArtifact) -> str:
    """Render the approved draft's content as a clean, deterministic markdown body.

    Pure function of ``artifact`` — safe to call repeatedly (publish idempotency) and in tests.
    """
    title = _KIND_TITLES.get(artifact.type, artifact.type.value)
    lines: list[str] = [f"# {title}({artifact.artifact_id})", ""]

    items = artifact.content.get("items") if isinstance(artifact.content, dict) else None
    if items:
        lines.extend(_item_line(item) for item in items)
    else:
        lines.append("(項目なし)")
    lines.append("")

    # Provenance section: the grounding evidence the draft was generated from (reference IDs).
    if artifact.source_document_ids or artifact.source_citations:
        lines.append("## 根拠")
        for doc_id in artifact.source_document_ids:
            lines.append(f"- 根拠ドキュメント: {doc_id}")
        for ref in artifact.source_citations:
            lines.append(f"- 引用: {ref}")
        lines.append("")

    lines.append(f"(承認済みドラフト {artifact.artifact_id} から公開)")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["render_draft_markdown"]
