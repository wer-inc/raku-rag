"""Shared tokenization. Content-word tokens (stopwords filtered) keep similarity/grounding honest.

Used by the embedding provider, groundedness gate and extractive LLM so that overlap on function
words ("the", "is") does not falsely satisfy retrieval/grounding.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"\w+", re.UNICODE)
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")

# Minimal English stopword set (function words). Japanese content is not space-split by \w+,
# so particle filtering is unnecessary for the MVP.
_STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "to",
    "of",
    "for",
    "and",
    "or",
    "in",
    "on",
    "at",
    "by",
    "with",
    "as",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "from",
    "into",
    "about",
    "what",
    "when",
    "where",
    "how",
    "why",
    "who",
    "which",
    "do",
    "does",
    "did",
    "i",
    "you",
    "he",
    "she",
    "they",
    "we",
    "me",
    "my",
    "your",
    "their",
    "per",
    "than",
    "then",
    "so",
    "not",
    "no",
    "yes",
    "can",
    "will",
    "would",
    "should",
    "could",
    "have",
    "has",
    "had",
    "but",
    "if",
    "out",
    "up",
    "down",
}


def content_tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOPWORDS]


def retrieval_tokens(text: str) -> list[str]:
    """Tokens for retrieval (embedding + lexical), Japanese-aware.

    ``\\w+`` runs of Japanese text carry no spaces, so the whole run becomes one token and "耐圧試験"
    never matches "耐圧試験の試験圧力". For runs containing CJK we emit character bigrams (so distinctive
    terms overlap and dominate cosine similarity over generic "magnet" docs); ASCII/alphanumeric runs
    (e.g. v, 205, mcc, loto, pwht) stay whole words so identifiers still match exactly. This is a
    retrieval-only tokenizer — ``content_tokens`` (and the safety classifier) are intentionally unchanged.
    """
    out: list[str] = []
    for tok in _WORD.findall(text.lower()):
        if _CJK.search(tok):
            chars = list(tok)
            if len(chars) == 1:
                out.append(chars[0])
            else:
                out.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
        elif tok not in _STOPWORDS:
            out.append(tok)
    return out


def content_terms(text: str) -> set[str]:
    """Terms used for grounding and extractive answers.

    Keep the original word tokens, then add the same CJK bigrams used by retrieval so Japanese
    evidence such as "担当部署は..." still supports a query containing "担当部署".
    Safety classification intentionally calls ``content_tokens`` directly, so this does not broaden
    high-risk keyword matching.
    """
    return set(content_tokens(text)) | set(retrieval_tokens(text))
