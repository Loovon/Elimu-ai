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


def is_anomaly_text(text: str) -> bool:
    """Identify generated failure messages, stack traces, and malformed content."""
    if text is None:
        return True
    cleaned = str(text).strip()
    if not cleaned:
        return True

    lower = cleaned.lower()
    if lower in {"null", "none", "undefined", "nan", "[object object]"}:
        return True

    failure_markers = [
        "elimu ai could not generate",
        "could not generate a response",
        "unable to generate",
        "failed to generate",
        "generation failed",
        "service unavailable",
        "temporarily unavailable",
        "please try again in a moment",
        "please try again shortly",
        "internal server error",
        "api error",
        "http error",
        "exception",
        "traceback",
        "stack trace",
        "python exception",
        "debug output",
        "raw tool output",
        "raw system instructions",
        "authentication error",
        "database error",
        "json fragment",
        "internal error",
        "unable to process",
        "not available right now",
    ]
    if any(marker in lower for marker in failure_markers):
        return True

    if "traceback (most recent call last)" in lower:
        return True

    if re.search(r"(?:^|\s)(?:error|exception|failed)(?:\s+to)?(?:\s+generate|\s+response|\s+request|\s+call)?\b", lower):
        context = lower.replace("\n", " ")
        if "what errors" not in context and "what error" not in context and "errors do students" not in context:
            return True

    if re.search(r"\{\s*\"?(?:title|body|message|error|status)\s*\"?\s*:\s*", lower):
        return True

    if re.search(r"\b(?:null|none|undefined|nan|\[object object\])\b", lower):
        return True

    if len(cleaned.split()) > 12 and cleaned.count(" ") > len(cleaned) / 3:
        tokens = re.findall(r"[a-z0-9]+", lower)
        if tokens and len(set(tokens)) <= 3:
            return True

    return False


def validate_generated_content(text: str, *, context: str = "response") -> bool:
    """Return True when generated content is safe to publish."""
    if text is None:
        logger.warning("moderation: %s rejected: content is None", context)
        return False

    cleaned = str(text).strip()
    if not cleaned:
        logger.warning("moderation: %s rejected: empty content", context)
        return False

    if is_anomaly_text(cleaned):
        logger.warning("moderation: %s rejected as anomalous output", context)
        return False

    if len(cleaned) < _MIN_LENGTH:
        logger.warning("moderation: %s rejected: too short", context)
        return False

    return True


def moderate(text: str) -> str:
    """
    Check text for spam / policy violations.
    Returns "Content approved." or a short rejection reason.
    """
    if not text or not text.strip():
        return "Content rejected: empty message."

    cleaned = text.strip()
    if not validate_generated_content(cleaned, context="moderation"):
        return "Content rejected: abnormal generation output."

    if len(cleaned) < _MIN_LENGTH:
        return "Content rejected: too short."

    lower = cleaned.lower()
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
