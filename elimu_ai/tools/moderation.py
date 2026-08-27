"""
elimu_ai/tools/moderation.py

Content moderation tool.
Responsibilities:
  - moderate(text) → "Content approved." | rejection reason string

Extend with Gemini-based semantic moderation when needed.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_SPAM_PATTERNS = [
    "buy now",
    "click here",
    "free money",
    "you have won",
    "congratulations you have won",
    "whatsapp me",
    "call me on",
    "send me your number",
    "guaranteed income",
    "make money fast",
]

_PROFANITY_PATTERNS = [
    r"\bfuck(?:ing|ed|er|s)?\b",
    r"\bshit(?:ty|ting|s)?\b",
    r"\basshole\b",
    r"\bbitch(?:es)?\b",
    r"\bbastard(?:s)?\b",
]

_MIN_LENGTH = 5


def moderate(text: str) -> str:
    """
    Check text for spam / policy violations.
    Returns "Content approved." or a short rejection reason.
    """
    if not text or not text.strip():
        return "Content rejected: empty message."

    if len(text.strip()) < _MIN_LENGTH:
        return "Content rejected: too short."

    lower = text.lower()
    for pattern in _SPAM_PATTERNS:
        if pattern in lower:
            logger.info("moderation: flagged text matching %r", pattern)
            return f"Content flagged: possible spam (matched: '{pattern}')."

    for pattern in _PROFANITY_PATTERNS:
        match = re.search(pattern, lower)
        if match:
            logger.info("moderation: flagged inappropriate language")
            return f"Content flagged: inappropriate language (matched: '{match.group()}')."

    return "Content approved."
