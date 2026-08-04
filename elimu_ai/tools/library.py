"""
elimu_ai/tools/library.py

Library tool — pure catalog lookup with intelligent audience filtering.
Responsibilities:
  - find_materials(...)        → formatted catalog results string
  - build_librarian_prompt(...)→ LIBRARIAN_PROMPT string for agent.py

Ranking priority:
  1. Exact grade + subject + audience + doctype
  2. Exact grade + subject
  3. Subject across all grades
  4. Keyword full-text search
  5. Category browse fallback links

Audience rules:
  - Student queries NEVER receive teacher-audience docs (schemes, designs)
    unless the question explicitly contains teacher-audience keywords.
  - Teacher queries always receive teacher-audience docs.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from elimu_ai.catalog_search import (
    _extract_from_keyword,
    _infer_audience_from_keyword,
    catalog_available,
    format_recommendations,
    search_catalog,
)
from elimu_ai.helpers import search_url
from elimu_ai.prompts import LIBRARIAN_PROMPT

logger = logging.getLogger(__name__)

# ── Category browse URLs ──────────────────────────────────────────────────────

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

# ── Doc-type inference ────────────────────────────────────────────────────────

_DOC_TYPE_MAP = {
    "scheme of work":    "schemesofwork",
    "schemes of work":   "schemesofwork",
    "scheme":            "schemesofwork",
    "schemes":           "schemesofwork",
    "record of work":    "recordofwork",
    "records of work":   "recordofwork",
    "curriculum design": "curriculumdesign",
    "curriculum designs":"curriculumdesign",
    "lesson plan":       "lessonplan",
    "lesson plans":      "lessonplan",
    "notes":             "notes",
    "revision notes":    "notes",
    "past paper":        "assessment",
    "past papers":       "assessment",
    "exam":              "assessment",
    "exams":             "assessment",
    "assessment":        "assessment",
    "assessment book":   "assessment",
    "homework":          "homework",
    "holiday homework":  "homework",
    "holiday booklet":   "homework",
    "homework booklet":  "homework",
    "booklet":           "homework",
    "revision":          "assessment",
    "topical":           "assessment",
    "rubric":            "rubric",
    "rubrics":           "rubric",
}


def _infer_doc_type(text: str) -> str:
    """Return normalised doc-type string inferred from text, or empty string."""
    t = text.lower()
    for kw, dt in sorted(_DOC_TYPE_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if kw in t:
            return dt
    return ""


def _category_fallback(ctx: Dict, doc_type: str, question: str) -> str:
    """Return category browse links when catalog search finds nothing."""
    grade_num: Optional[int] = None
    if ctx.get("grade"):
        m = re.search(r"\d+", ctx["grade"])
        if m:
            grade_num = int(m.group())

    lines = ["I couldn't find an exact match. Here are the best places to browse:", ""]

    aud = ctx.get("audience", "")

    # Teacher-specific category links
    if aud == "teacher" or doc_type in ("schemesofwork", "lessonplan", "curriculumdesign", "recordofwork"):
        lines.append("Schemes of Work: " + _CATEGORY_URLS["schemes"])
        lines.append("Lesson Plans: " + _CATEGORY_URLS["lesson_plans"])

    elif grade_num is not None:
        if grade_num <= 6:
            lines.append("Primary Exams: " + _CATEGORY_URLS["primary_exams"])
            lines.append("Primary Notes: " + _CATEGORY_URLS["primary_notes"])
        elif grade_num <= 9:
            lines.append("JSS Exams: " + _CATEGORY_URLS["jss_exams"])
            lines.append("JSS Notes: " + _CATEGORY_URLS["jss_notes"])
        else:
            lines.append("Secondary Exams: " + _CATEGORY_URLS["secondary_exams"])
            lines.append("Secondary Notes: " + _CATEGORY_URLS["secondary_notes"])
    else:
        lines.append("KCSE Revision: " + _CATEGORY_URLS["kcse_revision"])
        lines.append("Schemes of Work: " + _CATEGORY_URLS["schemes"])

    q = " ".join(p for p in [ctx.get("grade", ""), ctx.get("subject", "")] if p).strip() or question
    lines.append("")
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
    Multi-pass catalog search. Returns formatted plain-text results.

    Audience logic:
      - If audience is explicitly "teacher", returns teacher docs.
      - If audience is None or "student", teacher-audience docs are deprioritised.
      - Audience is inferred from the question if not provided.
    """
    # Build context dict
    ctx: Dict[str, Optional[str]] = {
        "grade": grade, "subject": subject,
        "term": term,   "year": year, "audience": audience,
    }

    # Fill from conversation history
    if history and not (ctx["grade"] and ctx["subject"]):
        from elimu_ai.tools.teacher import extract_context_from_history
        hist_ctx = extract_context_from_history(history[-6:])
        for key in ("grade", "subject", "term", "year", "audience"):
            if not ctx[key] and hist_ctx.get(key):
                ctx[key] = hist_ctx[key]

    # Fill from question keywords
    if not (ctx["grade"] and ctx["subject"]):
        kg, ks, kt, ky = _extract_from_keyword(question)
        if not ctx["grade"]   and kg: ctx["grade"]   = kg
        if not ctx["subject"] and ks: ctx["subject"] = ks
        if not ctx["term"]    and kt: ctx["term"]    = kt
        if not ctx["year"]    and ky: ctx["year"]    = ky

    # Infer doc type and audience
    doc_type = _infer_doc_type(question)
    if not ctx["audience"]:
        ctx["audience"] = _infer_audience_from_keyword(question) or None

    logger.debug(
        "Library search: grade=%s subject=%s term=%s year=%s audience=%s doctype=%s",
        ctx["grade"], ctx["subject"], ctx["term"], ctx["year"], ctx["audience"], doc_type,
    )

    # Clarification if we have nothing to work with
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

    def _add(new_results: List[Dict]) -> None:
        for r in new_results:
            url = r.get("url", "")
            if url and "/site/document/" in url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    g   = ctx["grade"]
    s   = ctx["subject"]
    t   = ctx["term"]
    y   = ctx["year"]
    aud = ctx["audience"]

    # Pass 1: Most specific — grade + subject + audience + doctype
    _add(search_catalog(grade=g, subject=s, term=t, year=y,
                        audience=aud, doctype=doc_type, max_results=5))

    # Pass 2: Grade + subject (relax doctype/audience)
    if len(all_results) < 3 and g and s:
        _add(search_catalog(grade=g, subject=s, term=t, year=y, max_results=5))

    # Pass 3: Subject across all grades
    if len(all_results) < 3 and s:
        _add(search_catalog(subject=s, audience=aud, doctype=doc_type, max_results=5))

    # Pass 4: Keyword fallback
    if len(all_results) < 2:
        _add(search_catalog(keyword=question, audience=aud, max_results=5))

    if all_results:
        # Filter out teacher-audience docs for student/unspecified requests
        if aud not in ("teacher",):
            student_results = [
                r for r in all_results if r.get("audience") != "teacher"
            ]
            # Only apply filter if it leaves at least 1 result
            if student_results:
                all_results = student_results

        # Build contextual header
        header = ""
        parts = [p for p in [g, s] if p]
        if parts:
            header = f"Here are the most relevant materials for {' '.join(parts)}"
            if t:   header += f" Term {t}"
            if y:   header += f" ({y})"
            if aud: header += f" — for {aud}s"
            header += ":\n\n"

        logger.info("Library: returning %d results for %r", len(all_results[:5]), question[:60])
        return header + format_recommendations(all_results[:5], question)

    logger.info("Library: no results found for %r — returning fallback", question[:60])
    return _category_fallback(ctx, doc_type, question)


def build_librarian_prompt(question: str, catalog_results: str = "") -> str:
    """
    Render the librarian persona prompt with catalog context embedded.
    Called by agent.py when the LLM needs to interpret catalog results.
    """
    return LIBRARIAN_PROMPT.format(
        context=catalog_results or "No catalog results found.",
        question=question,
    )
