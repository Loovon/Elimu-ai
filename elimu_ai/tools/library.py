"""
elimu_ai/tools/library.py

Library tool — pure catalog lookup.
Responsibilities:
  - find_materials(question, grade, subject, term, year, audience, history) → str

Rules:
  - Prefers exact catalog matches.
  - Never calls Gemini unless catalog is empty and a fallback prompt is needed.
  - Never imports service.py.
  - No circular imports — uses helpers, catalog_search, and prompts only.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import quote

from elimu_ai.catalog_search import (
    _extract_from_keyword,
    catalog_available,
    format_recommendations,
    search_catalog,
)
from elimu_ai.helpers import search_url
from elimu_ai.prompts import LIBRARIAN_PROMPT

# ── Category browse URLs (fallback when catalog has no exact match) ────────────

_CATEGORY_URLS = {
    "primary_exams":   "https://www.elimulibrary.com/site/category/4/exams-and-homework-pri",
    "jss_exams":       "https://www.elimulibrary.com/site/category/12/quizzes",
    "senior_exams":    "https://www.elimulibrary.com/site/category/34/senior-school-assessments-11-12-25-11-32-26",
    "secondary_exams": "https://www.elimulibrary.com/site/category/3/exams-and-homework-sec",
    "primary_notes":   "https://www.elimulibrary.com/site/category/6/primary-notes",
    "jss_notes":       "https://www.elimulibrary.com/site/category/30/jss-notes-topical-booklets",
    "senior_notes":    "https://www.elimulibrary.com/site/category/33/senior-school-notes-16-04-25-11-30-17",
    "secondary_notes": "https://www.elimulibrary.com/site/category/5/secondary-notes",
    "schemes":         "https://www.elimulibrary.com/site/category/1/schemes-of-work",
    "lesson_plans":    "https://www.elimulibrary.com/site/category/2/lesson-plans",
    "kcse_revision":   "https://www.elimulibrary.com/site/category/14/kcse-revision-exams",
    "topical_qs":      "https://www.elimulibrary.com/site/category/13/topical-questions",
    "homework":        "https://www.elimulibrary.com/site/category/27/holiday-homework-booklets",
}

_DOC_TYPE_MAP = {
    "scheme":         "scheme of work",
    "sow":            "scheme of work",
    "lesson plan":    "lesson plan",
    "lesson":         "lesson plan",
    "notes":          "notes",
    "note":           "notes",
    "revision notes": "notes",
    "past paper":     "assessment",
    "past papers":    "assessment",
    "exam":           "assessment",
    "assessment":     "assessment",
    "homework":       "homework",
    "holiday homework": "homework",
    "revision":       "assessment",
    "topical":        "assessment",
    "booklet":        "homework",
}

_AUDIENCE_MAP = {
    "teacher":  "teacher",
    "teachers": "teacher",
    "student":  "student",
    "students": "student",
    "learner":  "student",
    "parent":   "parent",
    "parents":  "parent",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _infer_doc_type(text: str) -> str:
    t = text.lower()
    for kw, dt in _DOC_TYPE_MAP.items():
        if kw in t:
            return dt
    return "assessment"


def _infer_audience(text: str) -> Optional[str]:
    t = text.lower()
    for kw, aud in _AUDIENCE_MAP.items():
        if kw in t:
            return aud
    if any(k in t for k in ["scheme", "lesson plan", "sow", "record of work", "i teach"]):
        return "teacher"
    if any(k in t for k in ["homework", "my child", "for my"]):
        return "parent"
    return None


def _category_fallback(ctx: Dict, doc_type: str, question: str) -> str:
    """Return category browse links when catalog search finds nothing."""
    grade_num = None
    if ctx.get("grade"):
        m = re.search(r"\d+", ctx["grade"])
        if m:
            grade_num = int(m.group())

    lines = ["I couldn't find an exact match, but here are the best places to browse:", ""]

    if grade_num is not None:
        if grade_num <= 6:
            lines.append("Primary Exams: " + _CATEGORY_URLS["primary_exams"])
            lines.append("Primary Notes: " + _CATEGORY_URLS["primary_notes"])
        elif grade_num <= 9:
            lines.append("JSS Exams: " + _CATEGORY_URLS["jss_exams"])
            lines.append("JSS Notes: " + _CATEGORY_URLS["jss_notes"])
        else:
            lines.append("Secondary Exams: " + _CATEGORY_URLS["secondary_exams"])
            lines.append("Secondary Notes: " + _CATEGORY_URLS["secondary_notes"])

    q = " ".join(p for p in [ctx.get("grade", ""), ctx.get("subject", "")] if p).strip() or question
    lines.append("Search Elimu Library: " + search_url(q))
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def find_materials(
    question: str,
    grade: Optional[str] = None,
    subject: Optional[str] = None,
    term: Optional[str] = None,
    year: Optional[str] = None,
    audience: Optional[str] = None,
    history: Optional[List[Dict]] = None,
) -> str:
    """
    Perform a multi-pass catalog search and return formatted results.

    Priority order:
      1. Exact grade + subject + audience + doctype
      2. Grade + subject
      3. Subject only across all grades
      4. Keyword fallback
      5. Category browse links
    """
    # Build context from arguments; fill gaps from keyword extraction
    ctx: Dict[str, Optional[str]] = {
        "grade":    grade,
        "subject":  subject,
        "term":     term,
        "year":     year,
        "audience": audience,
    }

    # Fill gaps from history if provided
    if history and not (ctx["grade"] and ctx["subject"]):
        from elimu_ai.tools.teacher import extract_context_from_history
        hist_ctx = extract_context_from_history(history[-6:])
        for key in ("grade", "subject", "term", "year", "audience"):
            if not ctx[key] and hist_ctx.get(key):
                ctx[key] = hist_ctx[key]

    # Fill gaps from the question itself
    if not (ctx["grade"] and ctx["subject"]):
        kg, ks, kt, ky = _extract_from_keyword(question)
        if not ctx["grade"] and kg:
            ctx["grade"] = kg
        if not ctx["subject"] and ks:
            ctx["subject"] = ks
        if not ctx["term"] and kt:
            ctx["term"] = kt
        if not ctx["year"] and ky:
            ctx["year"] = ky

    # Infer doc type and audience from the question
    doc_type = _infer_doc_type(question)
    if not ctx["audience"]:
        ctx["audience"] = _infer_audience(question)

    # Still nothing — ask for clarification
    if not ctx["subject"] and not ctx["grade"]:
        return (
            "I can find the exact materials for you! "
            "Could you tell me which subject and grade or form you need? "
            "For example: Grade 8 Mathematics, Form 3 Biology, or Grade 2 English."
        )

    if not catalog_available():
        q = " ".join(p for p in [ctx["grade"] or "", ctx["subject"] or ""] if p)
        return "Search the Elimu Library: " + search_url(q)

    # Multi-pass search
    all_results: List[Dict] = []
    seen_urls: set = set()

    def _add(new_results):
        for r in new_results:
            url = r.get("url", "")
            if url and "/site/document/" in url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    g = ctx["grade"]
    s = ctx["subject"]
    t = ctx["term"]
    y = ctx["year"]
    aud = ctx["audience"]

    # Pass 1: grade + subject + audience + doctype
    _add(search_catalog(grade=g, subject=s, term=t, year=y,
                        audience=aud, doctype=doc_type, max_results=5))

    # Pass 2: grade + subject (no doctype/audience filter)
    if len(all_results) < 3 and g and s:
        _add(search_catalog(grade=g, subject=s, term=t, year=y, max_results=5))

    # Pass 3: subject only across all grades
    if len(all_results) < 3 and s:
        _add(search_catalog(subject=s, audience=aud, doctype=doc_type, max_results=5))

    # Pass 4: keyword fallback
    if len(all_results) < 2:
        _add(search_catalog(keyword=question, max_results=5))

    if all_results:
        header_parts = [p for p in [g, s] if p]
        header = ""
        if header_parts:
            header = f"Here are the most relevant materials for {' '.join(header_parts)}"
            if t:
                header += f" Term {t}"
            if y:
                header += f" ({y})"
            if aud:
                header += f" — for {aud}s"
            header += ":\n\n"
        return header + format_recommendations(all_results[:5], question)

    return _category_fallback(ctx, doc_type, question)


def build_librarian_prompt(question: str, catalog_results: str = "") -> str:
    """
    Build a librarian prompt with catalog context already embedded.
    Used by agent.py when catalog results need an LLM to interpret them.
    """
    return LIBRARIAN_PROMPT.format(
        context=catalog_results or "No catalog results found.",
        question=question,
    )
