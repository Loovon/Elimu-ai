"""
elimu_ai/tools/teacher.py

Teacher tool — context extraction and prompt building only.
Responsibilities:
  - extract_context_hints(text)              → dict
  - extract_context_from_history(messages)   → dict
  - build_teacher_prompt(question, context, history) → str

Rules:
  - Never calls generate() or any Gemini function.
  - Never imports service.py.
  - Never makes network requests.
  - Only extracts metadata and builds prompt strings.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from elimu_ai.prompts import TEACHER_PROMPT
from elimu_ai.catalog_search import _SUBJECT_ALIASES

# ── Compiled patterns ─────────────────────────────────────────────────────────

_GRADE_RE   = re.compile(r"grade\s*(\d+|pp1|pp2)", re.I)
_PP_RE      = re.compile(r"\bpp(\d)\b", re.I)
_FORM_RE    = re.compile(r"\bform\s*(\d)\b", re.I)
_CLASS_RE   = re.compile(r"\bclass\s*(\d+)\b", re.I)
_TERM_RE    = re.compile(r"\bterm\s*(\d)\b", re.I)
_YEAR_RE    = re.compile(r"\b(20\d{2})\b")

# Subjects ordered longest-first so multi-word phrases match before single words
_KNOWN_SUBJECTS = sorted([
    "social studies", "integrated science", "environmental activities",
    "creative arts", "pre-technical studies", "agriculture and nutrition",
    "mathematics activities", "english activities", "kiswahili activities",
    "mathematics", "english", "kiswahili", "biology", "chemistry", "physics",
    "history", "geography", "cre", "ire", "business studies",
    "computer studies", "agriculture", "science",
    "general science", "power mechanics", "music and dance",
], key=len, reverse=True)

_AUDIENCE_MAP = {
    "teacher":  ["teacher", "scheme", "lesson plan", "sow", "record of work",
                 "i teach", "curriculum design", "rubric"],
    "parent":   ["parent", "homework", "my child", "for my"],
    "student":  ["student", "exam", "revision", "learner", "notes", "booklet"],
}


# ── Public functions ──────────────────────────────────────────────────────────

def extract_context_hints(text: str) -> Dict[str, Optional[str]]:
    """
    Extract grade, subject, term, year, and audience from free text.
    Returns a dict — any field may be None if not detected.
    """
    lower = text.lower()
    ctx: Dict[str, Optional[str]] = {
        "grade": None, "subject": None,
        "term": None,  "year": None, "audience": None,
    }

    # Grade
    m = _GRADE_RE.search(lower)
    if m:
        ctx["grade"] = f"grade{m.group(1).lower().replace(' ', '')}"
    elif (m := _PP_RE.search(lower)):
        ctx["grade"] = f"gradepp{m.group(1)}"
    elif (m := _FORM_RE.search(lower)):
        ctx["grade"] = f"form{m.group(1)}"
    elif (m := _CLASS_RE.search(lower)):
        ctx["grade"] = f"grade{m.group(1)}"

    # Term & year
    if (m := _TERM_RE.search(lower)):
        ctx["term"] = m.group(1)
    if (m := _YEAR_RE.search(lower)):
        ctx["year"] = m.group(1)

    # Subject — longest match wins
    for subj in _KNOWN_SUBJECTS:
        if subj in lower:
            ctx["subject"] = subj.replace(" ", "")
            break

    # Subject alias fallback
    if not ctx["subject"]:
        for alias, canonical in _SUBJECT_ALIASES.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", lower):
                ctx["subject"] = canonical
                break

    # Audience
    for aud, keywords in _AUDIENCE_MAP.items():
        if any(kw in lower for kw in keywords):
            ctx["audience"] = aud
            break

    return ctx


def extract_context_from_history(messages: List[Dict]) -> Dict[str, Optional[str]]:
    """
    Merge context hints across a list of {role, content} message dicts.
    Later messages take priority over earlier ones.
    """
    merged: Dict[str, Optional[str]] = {
        "grade": None, "subject": None,
        "term": None,  "year": None, "audience": None,
    }
    for msg in messages:
        hints = extract_context_hints(msg.get("content", ""))
        for key, val in hints.items():
            if val:
                merged[key] = val
    return merged


def build_teacher_prompt(
    question: str,
    context: str = "",
    history: Optional[List[Dict]] = None,
) -> str:
    """
    Render and return the teacher persona prompt.
    Does NOT call Gemini.
    """
    _ = history  # reserved for future multi-turn expansion
    return TEACHER_PROMPT.format(
        context=context or "No additional context available.",
        question=question,
    )
