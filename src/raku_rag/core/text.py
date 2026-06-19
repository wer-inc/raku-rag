"""Shared tokenization. Content-word tokens (stopwords filtered) keep similarity/grounding honest.

Used by the embedding provider, groundedness gate and extractive LLM so that overlap on function
words ("the", "is") does not falsely satisfy retrieval/grounding.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"\w+", re.UNICODE)

# Minimal English stopword set (function words). Japanese content is not space-split by \w+,
# so particle filtering is unnecessary for the MVP.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "for", "and", "or", "in", "on", "at", "by", "with", "as",
    "that", "this", "these", "those", "it", "its", "from", "into", "about",
    "what", "when", "where", "how", "why", "who", "which", "do", "does", "did",
    "i", "you", "he", "she", "they", "we", "me", "my", "your", "their",
    "per", "than", "then", "so", "not", "no", "yes", "can", "will", "would",
    "should", "could", "have", "has", "had", "but", "if", "out", "up", "down",
}


def content_tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOPWORDS]


def content_terms(text: str) -> set[str]:
    return set(content_tokens(text))
