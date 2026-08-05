"""
elimu_ai/intent.py

Multi-intent detection with confidence scoring.

Replaces single-persona keyword routing with a multi-intent system
that can detect multiple simultaneous intents from one message.

Example:
    "Recommend chemistry notes then quiz me"
    → [IntentResult("recommendation", 0.9), IntentResult("quiz", 0.85)]

Intents:
    teacher         — explain a concept
    quiz            — generate practice questions
    community       — forum / discussion
    librarian       — find documents in Elimu Library
    search          — general search request
    recommendation  — recommend materials
    discussion      — start or find a discussion
    moderation      — flag or report content
    catalog         — browse catalog
    general_chat    — casual / off-topic conversation

Rules:
  - No Gemini. No Qdrant. Pure text matching + confidence scoring.
  - Returns a sorted list of IntentResult, highest confidence first.
  - Primary intent = result[0].name
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(order=True)
class IntentResult:
    """A detected intent and its confidence score (0.0 – 1.0)."""
    confidence: float
    name: str = field(compare=False)
    matched_signals: List[str] = field(default_factory=list, compare=False)

    def __repr__(self) -> str:
        return f"IntentResult({self.name!r}, {self.confidence:.2f})"


# ── Signal tables ─────────────────────────────────────────────────────────────
# Each entry: (pattern_or_keyword, weight, is_regex)

_QUIZ_SIGNALS = [
    ("quiz me",               0.95, False),
    ("test me",               0.95, False),
    ("give me a quiz",        0.90, False),
    ("generate a quiz",       0.90, False),
    ("give me questions",     0.85, False),
    ("generate questions",    0.85, False),
    ("past paper questions",  0.85, False),
    ("practice questions",    0.80, False),
    ("practise questions",    0.80, False),
    ("multiple choice",       0.75, False),
    ("mcq",                   0.75, False),
    (r"\bquiz\b",             0.70, True),
    ("exam questions",        0.70, False),
]

_TEACHER_SIGNALS = [
    ("explain",               0.80, False),
    ("what is",               0.75, False),
    ("how does",              0.75, False),
    ("how do",                0.70, False),
    ("teach me",              0.85, False),
    ("help me understand",    0.80, False),
    ("describe",              0.70, False),
    ("define",                0.75, False),
    ("difference between",    0.70, False),
    ("why is",                0.65, False),
    ("what are",              0.60, False),
]

_LIBRARIAN_SIGNALS = [
    ("schemes of work",       0.95, False),
    ("scheme of work",        0.95, False),
    ("record of work",        0.90, False),
    ("curriculum design",     0.90, False),
    ("lesson plan",           0.90, False),
    ("past paper",            0.85, False),
    ("assessment book",       0.85, False),
    ("holiday homework",      0.85, False),
    ("revision materials",    0.80, False),
    ("find me",               0.75, False),
    ("where can i get",       0.75, False),
    ("do you have",           0.70, False),
    ("download",              0.65, False),
    (r"\bnotes\b",            0.60, True),
    (r"\bexams?\b",           0.60, True),
    ("revision",              0.55, False),
    ("homework",              0.55, False),
    ("booklet",               0.55, False),
]

_RECOMMENDATION_SIGNALS = [
    ("recommend",             0.90, False),
    ("suggest",               0.85, False),
    ("recommend me",          0.90, False),
    ("what should i",         0.75, False),
    ("best materials",        0.80, False),
    ("best notes",            0.80, False),
    ("which notes",           0.70, False),
    ("any good",              0.65, False),
    ("what books",            0.65, False),
]

_COMMUNITY_SIGNALS = [
    ("create a post",         0.95, False),
    ("start a thread",        0.95, False),
    ("start a discussion",    0.90, False),
    ("what does everyone think", 0.90, False),
    (r"\bforum\b",            0.85, True),
    (r"\bdiscussion\b",       0.70, True),
    (r"\bcommunity\b",        0.65, True),
    (r"\bdebate\b",           0.70, True),
]

_DISCUSSION_SIGNALS = [
    ("discuss",               0.80, False),
    ("thoughts on",           0.75, False),
    ("opinion on",            0.75, False),
    ("what do you think",     0.75, False),
    ("talk about",            0.65, False),
    ("let's talk",            0.65, False),
]

_CATALOG_SIGNALS = [
    ("catalog",               0.85, False),
    ("catalogue",             0.85, False),
    ("elimu library",         0.80, False),
    ("elimulibrary",          0.80, False),
    ("browse",                0.65, False),
    ("list of",               0.60, False),
    ("show me all",           0.65, False),
    ("what is available",     0.60, False),
]

_SEARCH_SIGNALS = [
    ("search for",            0.80, False),
    ("look up",               0.75, False),
    ("find information",      0.70, False),
    ("search",                0.55, False),
    ("look for",              0.60, False),
]

_MODERATION_SIGNALS = [
    ("report this",           0.90, False),
    ("flag this",             0.90, False),
    ("spam",                  0.75, False),
    ("inappropriate",         0.80, False),
    ("moderate",              0.75, False),
    ("remove this",           0.70, False),
]

_GENERAL_CHAT_SIGNALS = [
    ("hello",                 0.80, False),
    ("hi there",              0.80, False),
    ("how are you",           0.75, False),
    ("good morning",          0.75, False),
    ("good afternoon",        0.75, False),
    ("thanks",                0.60, False),
    ("thank you",             0.60, False),
    ("who are you",           0.80, False),
    ("what can you do",       0.75, False),
]

# Intent → signal table
_INTENT_SIGNALS = {
    "quiz":          _QUIZ_SIGNALS,
    "teacher":       _TEACHER_SIGNALS,
    "librarian":     _LIBRARIAN_SIGNALS,
    "recommendation":_RECOMMENDATION_SIGNALS,
    "community":     _COMMUNITY_SIGNALS,
    "discussion":    _DISCUSSION_SIGNALS,
    "catalog":       _CATALOG_SIGNALS,
    "search":        _SEARCH_SIGNALS,
    "moderation":    _MODERATION_SIGNALS,
    "general_chat":  _GENERAL_CHAT_SIGNALS,
}

# Minimum confidence threshold to include an intent in results
_MIN_CONFIDENCE: float = 0.45

# Maximum number of intents to return per request
_MAX_INTENTS: int = 4


# ── Public API ────────────────────────────────────────────────────────────────

def detect_intents(
    text: str,
    min_confidence: float = _MIN_CONFIDENCE,
    max_intents: int = _MAX_INTENTS,
) -> List[IntentResult]:
    """
    Detect all intents present in the text, sorted by confidence (highest first).

    Parameters
    ----------
    text : str
        The user's message.
    min_confidence : float
        Minimum score for an intent to be included.
    max_intents : int
        Maximum number of intents to return.

    Returns
    -------
    List[IntentResult]
        Sorted list of detected intents. Always contains at least one entry.
    """
    lower = text.lower().strip()
    results: List[IntentResult] = []

    for intent_name, signals in _INTENT_SIGNALS.items():
        score = 0.0
        matched: List[str] = []

        for pattern, weight, is_regex in signals:
            if is_regex:
                if re.search(pattern, lower):
                    score = max(score, weight)
                    matched.append(pattern)
            else:
                if pattern in lower:
                    score = max(score, weight)
                    matched.append(pattern)

        if score >= min_confidence:
            results.append(IntentResult(
                name=intent_name,
                confidence=score,
                matched_signals=matched,
            ))

    # Sort by confidence descending
    results.sort(reverse=True)

    # Always return at least "teacher" as fallback
    if not results:
        results.append(IntentResult(
            name="teacher",
            confidence=0.40,
            matched_signals=[],
        ))

    return results[:max_intents]


def primary_intent(text: str) -> str:
    """
    Return the single highest-confidence intent name.
    Backward-compatible replacement for decide_persona().
    """
    intents = detect_intents(text)
    return intents[0].name


def has_intent(text: str, intent: str, min_confidence: float = _MIN_CONFIDENCE) -> bool:
    """Return True if the given intent is detected above min_confidence."""
    for r in detect_intents(text):
        if r.name == intent and r.confidence >= min_confidence:
            return True
    return False


def intent_names(text: str, min_confidence: float = _MIN_CONFIDENCE) -> List[str]:
    """Return the list of detected intent names sorted by confidence."""
    return [r.name for r in detect_intents(text, min_confidence=min_confidence)]
