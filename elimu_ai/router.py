"""
elimu_ai/router.py

Persona router — maps an incoming question to the right persona.
Responsibilities:
  - decide_persona(question) → "quiz" | "community" | "librarian" | "teacher"

Rules:
  - Keyword-only routing. No Gemini. No Qdrant. No business logic.
  - Keyword lists are ordered: more specific first, fallback last.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Quiz keywords ─────────────────────────────────────────────────────────────
# Explicit requests for questions / tests — distinct from finding materials.

_QUIZ_KEYWORDS = [
    "quiz me",
    "test me",
    "give me questions",
    "generate questions",
    "exam questions",
    "practice questions",
    "practise questions",
    "past paper questions",
    "multiple choice",
    "mcq",
    r"\bquiz\b",           # "quiz" as a standalone word (regex)
]

# ── Community / discussion keywords ──────────────────────────────────────────

_COMMUNITY_KEYWORDS = [
    "create a post",
    "start a thread",
    "start a discussion",
    "what does everyone think",
    r"\bforum\b",
    r"\bdiscussion\b",
    r"\bcommunity\b",
    r"\bdebate\b",
]

# ── Library / document-finding keywords ──────────────────────────────────────
# Covers all the sample queries: schemes, record of work, curriculum designs,
# assessment books, holiday homework, lesson plans, revision papers, etc.

_LIBRARIAN_PLAIN = [
    # Document type names (these alone are strong librarian signals)
    "schemes of work",
    "scheme of work",
    "record of work",
    "records of work",
    "curriculum design",
    "curriculum designs",
    "lesson plan",
    "lesson plans",
    "assessment book",
    "assessment books",
    "holiday homework",
    "holiday booklet",
    "homework booklet",
    "homework book",
    "past paper",
    "past papers",
    "topical questions",
    "revision papers",
    "revision materials",
    "revision exams",
    "kcse revision",
    "end term",
    "opener exams",
    "school report book",
    "report book",
    # Action verbs / intent phrases
    "find me",
    "get me",
    "i need",
    "i want",
    "looking for",
    "where can i",
    "do you have",
    "send me",
    "share",
    "download",
    "free download",
    "pdf download",
    "pdf free",
    # Generic document nouns
    "notes",
    "booklet",
    "materials",
    "resources",
    "exams",
    "assessment",
    "revision",
    "topical",
    "homework",
    "buy",
    "purchase",
    "price",
    "what is the pricing",
    "elimu library",
    "elimulibrary",
    "elimu notes",
    "elimu exams",
    "elimu free",
    "elimu revision",
    "elimu kenya",
    "elimu cloud",
    "elimucloud",
    "elimu fiti",
    "elimu website",
    "elimu centre",
    "easy elimu",
    "easymwalimu",
    "schemes online",
    # CBC-specific document types
    "rubric",
    "rubrics",
    "project",
    "authentic task",
    "sub strand",
    "record of work covered",
    # Specific Kenyan exam bodies / publishers
    "kcse",
    "kpsea",
    "kjsea",
    "csl grade",
    "hero cluster",
    "grade master",
    "royal college",
    "smart minds",
    "spotlight",
    "klb",
    "teachers arena",
    "grade six exam",
    "grade one exam",
    "jss exam",
    "jss notes",
    "jss exams",
    "play group",
    "playgroup",
    "pp1",
    "pp2",
]

# Regex-based library patterns (word boundary matches)
_LIBRARIAN_REGEX = [
    r"\bscheme\b",
    r"\bschemes\b",
    r"\bnotes\b",
    r"\bexam\b",
    r"\bexams\b",
    r"\bpaper\b",
    r"\bpapers\b",
    r"\bworkbook\b",
    r"\bbooklet\b",
    r"\bhomework\b",
    r"\blink\b",
]


def decide_persona(question: str) -> str:
    """
    Determine the persona best suited to handle the question.

    Returns one of:
        "quiz"      — generate practice questions / tests
        "community" — forum discussion / post creation
        "librarian" — find documents / materials in Elimu Library
        "teacher"   — explain a concept / answer an educational question
    """
    text  = question.lower().strip()
    lower = text  # alias for readability

    # ── Quiz ─────────────────────────────────────────────────────────────────
    for kw in _QUIZ_KEYWORDS:
        if kw.startswith(r"\b"):
            if re.search(kw, lower):
                logger.debug("Router: quiz (regex match %r)", kw)
                return "quiz"
        elif kw in lower:
            logger.debug("Router: quiz (plain match %r)", kw)
            return "quiz"

    # ── Community ─────────────────────────────────────────────────────────────
    for kw in _COMMUNITY_KEYWORDS:
        if kw.startswith(r"\b"):
            if re.search(kw, lower):
                logger.debug("Router: community (regex match %r)", kw)
                return "community"
        elif kw in lower:
            logger.debug("Router: community (plain match %r)", kw)
            return "community"

    # ── Librarian ─────────────────────────────────────────────────────────────
    for kw in _LIBRARIAN_PLAIN:
        if kw in lower:
            logger.debug("Router: librarian (plain match %r)", kw)
            return "librarian"

    for kw in _LIBRARIAN_REGEX:
        if re.search(kw, lower):
            logger.debug("Router: librarian (regex match %r)", kw)
            return "librarian"

    # ── Teacher (default) ─────────────────────────────────────────────────────
    logger.debug("Router: teacher (default)")
    return "teacher"
