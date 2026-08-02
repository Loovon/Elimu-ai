"""
elimu_ai/tools/moderation.py

Moderation tool — content safety checks.
Responsibilities:
  - moderate(text) → str   ("approved" | reason for rejection)

Extend this module with Gemini-based moderation when needed.
"""

from __future__ import annotations


_SPAM_PATTERNS = [
    "buy now",
    "click here",
    "free money",
    "winner",
    "congratulations you have won",
    "whatsapp me",
    "call me on",
]


def moderate(text: str) -> str:
    """
    Basic content moderation check.
    Returns "Content approved." or a rejection reason.
    """
    if not text or not text.strip():
        return "Content rejected: empty message."

    lower = text.lower()
    for pattern in _SPAM_PATTERNS:
        if pattern in lower:
            return f"Content flagged: possible spam (matched: '{pattern}')."

    if len(text) < 5:
        return "Content rejected: too short."

    return "Content approved."
