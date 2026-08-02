"""
elimu_ai/router.py

Persona router — decides which persona should handle a request.
Responsibilities:
  - decide_persona(question) → str

No Gemini.  No Qdrant.  No business logic.
Only keyword-based routing.
"""

from __future__ import annotations


# ── Keyword lists ─────────────────────────────────────────────────────────────

_QUIZ_KEYWORDS = [
    "quiz", "test me", "give me questions", "mcq", "multiple choice",
    "practice questions", "practise questions", "generate questions",
    "exam questions", "past paper questions",
]

_COMMUNITY_KEYWORDS = [
    "forum", "discussion", "create a post", "start a thread",
    "community", "debate", "what does everyone think",
]

_LIBRARIAN_KEYWORDS = [
    "find", "get me", "i need", "looking for", "where can i",
    "do you have", "download", "recommend", "notes", "past paper",
    "assessment", "scheme", "lesson plan", "homework", "booklet",
    "materials", "resources", "revision", "topical", "send me",
    "share", "link", "buy", "purchase",
    "need notes", "need exam", "need assessment",
    "need scheme", "need revision", "need past",
]


# ── Public API ────────────────────────────────────────────────────────────────

def decide_persona(question: str) -> str:
    """
    Return one of: "quiz" | "community" | "librarian" | "teacher"
    based on keyword matching against the question.
    """
    text = question.lower()

    if any(kw in text for kw in _QUIZ_KEYWORDS):
        return "quiz"

    if any(kw in text for kw in _COMMUNITY_KEYWORDS):
        return "community"

    if any(kw in text for kw in _LIBRARIAN_KEYWORDS):
        return "librarian"

    return "teacher"
