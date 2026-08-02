"""
elimu_ai/tools/teacher.py

Teacher tool — builds the prompt for the teacher persona.
Responsibilities:
  - build_teacher_prompt(question, context, history) → str
  - extract_context_hints(text)                      → dict

Rules:
  - NEVER calls ask_ai() / generate() directly.
  - NEVER imports service.py.
  - NEVER makes HTTP requests.
  - Only builds and returns prompt strings or extracted metadata dicts.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from elimu_ai.prompts import TEACHER_PROMPT
from elimu_ai.catalog_search import _SUBJECT_ALIASES


# ── Grade / subject / term extraction ─────────────────────────────────────────

_GRADE_PATTERNS = [
    r"grade\s*(\d+|pp1|pp2)",
    r"\bpp(\d)\b",
    r"form\s*(\d)",
    r"\bclass\s*(\d+)\b",
]

_TERM_PATTERN = re.compile(r"\bterm\s*(\d)\b", re.I)
_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")

_KNOWN_SUBJECTS = [
    "social studies", "integrated science", "environmental activities",
    "creative arts", "pre-technical studies", "agriculture and nutrition",
    "mathematics activities", "english activities", "kiswahili activities",
    "mathematics", "english", "kiswahili", "biology", "chemistry", "physics",
    "history", "geography", "cre", "ire", "business studies",
    "computer studies", "agriculture", "science",
]

_AUDIENCE_KEYWORDS = {
    "teacher":  ["teacher", "scheme", "lesson plan", "sow", "record of work", "i teach"],
    "parent":   ["parent", "homework", "my child", "for my"],
    "student":  ["student", "exam", "revision", "learner"],
}


def extract_context_hints(text: str) -> Dict[str, Optional[str]]:
    """
    Extract grade, subject, term, year, and audience hints from free text.
    Returns a dict — any key may be None if not found.
    """
    lower = text.lower()
    ctx: Dict[str, Optional[str]] = {
        "grade": None,
        "subject": None,
        "term": None,
        "year": None,
        "audience": None,
    }

    # Grade
    for pat in _GRADE_PATTERNS:
        m = re.search(pat, lower, re.I)
        if m:
            raw = m.group(1) if m.lastindex else m.group(0)
            ctx["grade"] = f"grade{raw.lower().replace(' ', '')}"
            break

    # Form (secondary)
    if not ctx["grade"]:
        m = re.search(r"\bform\s*(\d)\b", lower, re.I)
        if m:
            ctx["grade"] = f"form{m.group(1)}"

    # Term
    m = _TERM_PATTERN.search(lower)
    if m:
        ctx["term"] = m.group(1)

    # Year
    m = _YEAR_PATTERN.search(lower)
    if m:
        ctx["year"] = m.group(1)

    # Subject — longest match first to prefer "social studies" over "studies"
    for subj in sorted(_KNOWN_SUBJECTS, key=len, reverse=True):
        if subj in lower:
            ctx["subject"] = subj.replace(" ", "")
            break

    # Subject aliases
    if not ctx["subject"]:
        for alias, canonical in _SUBJECT_ALIASES.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", lower):
                ctx["subject"] = canonical
                break

    # Audience
    for aud, keywords in _AUDIENCE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            ctx["audience"] = aud
            break

    return ctx


def extract_context_from_history(messages: List[Dict]) -> Dict[str, Optional[str]]:
    """
    Merge context hints across a list of message dicts {role, content}.
    Earlier messages have lower priority than later ones.
    """
    merged: Dict[str, Optional[str]] = {
        "grade": None, "subject": None, "term": None, "year": None, "audience": None,
    }
    for msg in messages:
        hints = extract_context_hints(msg.get("content", ""))
        for key, val in hints.items():
            if val:
                merged[key] = val
    return merged


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_teacher_prompt(
    question: str,
    context: str = "",
    history: Optional[List[Dict]] = None,
) -> str:
    """
    Build and return a teacher persona prompt string.
    Does NOT call Gemini.
    """
    _ = history  # available for future multi-turn prompt expansion
    return TEACHER_PROMPT.format(
        context=context or "No additional context available.",
        question=question,
    )
