"""
elimu_ai/tools/library.py

Library tool — semantic RAG search + structured metadata filtering.

Pipeline:
  1. Parse query → structured sub-queries (grade/subject/term/etc.)
  2. Qdrant semantic search with metadata pre-filters (per sub-query)
  3. Catalog flat-file fallback if Qdrant returns nothing
  4. Evidence reranking (exact field matches score higher)
  5. Format structured recommendations from evidence payloads
  6. URLs come ONLY from retrieved payloads — never invented

Rules:
  - Never invent document titles, URLs, prices, or catalogue records.
  - Students never receive teacher-audience docs unless explicitly requested.
  - build_librarian_prompt() is for Gemini context — URLs are still from evidence.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from elimu_ai.catalog_search import (
    _extract_from_keyword,
    _infer_audience_from_keyword,
    catalog_available,
    format_recommendations,
    search_catalog,
    _add_ref,
)
from elimu_ai.helpers import search_url
from elimu_ai.prompts import LIBRARIAN_PROMPT

logger = logging.getLogger(__name__)

_CATEGORY_URLS = {
    "primary_exams":   "https://www.elimulibrary.com/site/category/4/exams-and-homework-pri",
    "jss_exams":       "https://www.elimulibrary.com/site/category/12/quizzes",
    "secondary_exams": "https://www.elimulibrary.com/site/category/3/exams-and-homework-sec",
    "primary_notes":   "https://www.elimulibrary.com/site/category/6/primary-notes",
    "jss_notes":       "https://www.elimulibrary.com/site/category/30/jss-notes-topical-booklets",
    "secondary_notes": "https://www.elimulibrary.com/site/category/5/secondary-notes",
    "schemes":         "https://www.elimulibrary.com/site/category/1/schemes-of-work",
    "lesson_plans":    "https://www.elimulibrary.com/site/category/2/lesson-plans",
    "kcse_revision":   "https://www.elimulibrary.com/site/category/14/kcse-revision-exams",
    "topical_qs":      "https://www.elimulibrary.com/site/category/13/topical-questions",
    "homework":        "https://www.elimulibrary.com/site/category/27/holiday-homework-booklets",
}

_DOC_TYPE_MAP = {
    "scheme of work": "schemesofwork", "schemes of work": "schemesofwork",
    "scheme": "schemesofwork", "schemes": "schemesofwork",
    "record of work": "recordofwork", "curriculum design": "curriculumdesign",
    "lesson plan": "lessonplan", "lesson plans": "lessonplan",
    "notes": "notes", "revision notes": "notes",
    "past paper": "assessment", "past papers": "assessment",
    "exam": "assessment", "exams": "assessment", "assessment": "assessment",
    "homework": "homework", "holiday homework": "homework",
    "booklet": "homework", "revision": "assessment", "topical": "assessment",
    "rubric": "rubric", "rubrics": "rubric",
}


def _infer_doc_type(text: str) -> str:
    t = text.lower()
    for kw, dt in sorted(_DOC_TYPE_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if kw in t:
            return dt
    return ""


def _rerank_evidence(
    results: List[Dict[str, Any]],
    grade: Optional[str],
    subject: Optional[str],
    term: Optional[str],
    audience: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Re-rank evidence records so exact field matches score higher.
    Rules:
      +4  exact grade match
      +4  exact subject match
      +3  exact term match
      +2  exact audience match
      -3  teacher-audience doc returned to student/unspecified
    """
    def _score(r: Dict[str, Any]) -> float:
        base = r.get("score", 0.0)
        bonus = 0
        r_grade   = (r.get("grade") or "").lower().replace(" ", "")
        r_subject = (r.get("subject") or "").lower().replace(" ", "")
        r_term    = str(r.get("term") or "").strip()
        r_aud     = (r.get("audience") or "").lower()

        if grade   and grade.lower().replace(" ", "") == r_grade:   bonus += 4
        if subject and subject.lower().replace(" ", "") == r_subject: bonus += 4
        if term    and str(term).strip() == r_term:                 bonus += 3
        if audience and audience.lower() == r_aud:                  bonus += 2
        if r_aud == "teacher" and audience in (None, "student", ""):
            bonus -= 3
        return base + bonus

    return sorted(results, key=_score, reverse=True)


def _qdrant_search_for_query(
    grade: Optional[str],
    subject: Optional[str],
    term: Optional[str],
    year: Optional[str],
    audience: Optional[str],
    doc_type: Optional[str],
    question: str,
) -> List[Dict[str, Any]]:
    """Run Qdrant semantic search with metadata filters for one sub-query."""
    try:
        from elimu_ai.qdrant_db import search, _build_filter
        from elimu_ai.config import COLLECTION_NAME, RAG_CANDIDATES

        filters: Dict[str, Any] = {}
        if grade:    filters["grade"]    = grade
        if subject:  filters["subject"]  = subject
        if term:     filters["term"]     = term
        if audience: filters["audience"] = audience

        search_text = " ".join(p for p in [
            grade, subject, f"Term {term}" if term else "",
            doc_type, year, question,
        ] if p)

        hits = search(search_text, limit=RAG_CANDIDATES, filters=filters,
                      collection=COLLECTION_NAME)
        if not hits and (filters or True):
            # Retry without filters (semantic only)
            hits = search(search_text, limit=RAG_CANDIDATES, collection=COLLECTION_NAME)

        records = []
        for h in hits:
            p = h.payload or {}
            url = p.get("url") or p.get("referral_url") or ""
            if url:
                records.append({
                    "source":   "qdrant",
                    "score":    h.score,
                    "title":    p.get("title", ""),
                    "url":      url,
                    "grade":    p.get("grade", grade),
                    "subject":  p.get("subject", subject),
                    "term":     p.get("term", term),
                    "year":     p.get("year", year),
                    "doctype":  p.get("doctype", doc_type),
                    "audience": p.get("audience", audience),
                    "price":    p.get("price"),
                    "description": p.get("description", ""),
                    "curriculum":  p.get("curriculum", ""),
                })
        return records
    except Exception as exc:
        logger.warning("Qdrant search failed for sub-query: %s", exc)
        return []


def _catalog_search_for_query(
    grade, subject, term, year, audience, doc_type, question, limit=10,
) -> List[Dict[str, Any]]:
    """Flat-catalog fallback."""
    if not catalog_available():
        return []
    try:
        docs = search_catalog(
            grade=grade, subject=subject, term=term, year=year,
            doctype=doc_type, audience=audience, keyword=question,
            max_results=limit,
        )
        records = []
        for d in docs:
            url = d.get("url", "")
            if url:
                records.append({
                    "source":   "catalog",
                    "score":    0.0,
                    "title":    d.get("title", ""),
                    "url":      _add_ref(url),
                    "grade":    d.get("grade", grade),
                    "subject":  d.get("subject", subject),
                    "term":     d.get("term", term),
                    "year":     d.get("year", year),
                    "doctype":  d.get("doctype", doc_type),
                    "audience": d.get("audience", audience),
                    "price":    d.get("price"),
                    "description": d.get("description", ""),
                    "curriculum":  d.get("curriculum", ""),
                })
        return records
    except Exception as exc:
        logger.warning("Catalog fallback failed: %s", exc)
        return []


def _category_fallback(ctx: Dict, doc_type: str, question: str) -> str:
    grade_num: Optional[int] = None
    if ctx.get("grade"):
        m = re.search(r"\d+", str(ctx["grade"]))
        if m:
            grade_num = int(m.group())
    aud = ctx.get("audience", "")
    lines = ["I couldn't find an exact match. Here are the best places to browse:", ""]
    if aud == "teacher" or doc_type in ("schemesofwork", "lessonplan", "curriculumdesign", "recordofwork"):
        lines.append("Schemes of Work: " + _CATEGORY_URLS["schemes"])
        lines.append("Lesson Plans: " + _CATEGORY_URLS["lesson_plans"])
    elif grade_num is not None:
        if grade_num <= 6:
            lines.extend(["Primary Exams: " + _CATEGORY_URLS["primary_exams"],
                          "Primary Notes: " + _CATEGORY_URLS["primary_notes"]])
        elif grade_num <= 9:
            lines.extend(["JSS Exams: " + _CATEGORY_URLS["jss_exams"],
                          "JSS Notes: " + _CATEGORY_URLS["jss_notes"]])
        else:
            lines.extend(["Secondary Exams: " + _CATEGORY_URLS["secondary_exams"],
                          "Secondary Notes: " + _CATEGORY_URLS["secondary_notes"]])
    else:
        lines.extend(["KCSE Revision: " + _CATEGORY_URLS["kcse_revision"],
                      "Schemes of Work: " + _CATEGORY_URLS["schemes"]])
    q = " ".join(p for p in [ctx.get("grade",""), ctx.get("subject","")] if p).strip() or question
    lines += ["", "Search Elimu Library: " + search_url(q)]
    return "\n".join(lines)


def _format_evidence(records: List[Dict[str, Any]], question: str = "") -> str:
    """Format evidence records as clean plain text with preserved URLs."""
    if not records:
        return ""
    lines = [f"Here are the best matching materials from the Elimu Library ({len(records)} found):", ""]
    for i, r in enumerate(records, 1):
        title    = (r.get("title") or "Document").title()
        url      = r.get("url", "")
        price    = r.get("price") or "KES 100"
        aud      = r.get("audience", "")
        doctype  = r.get("doctype", "")
        desc     = r.get("description", "")
        parts = [p for p in [r.get("year"), r.get("grade"), r.get("subject"),
                              f"Term {r['term']}" if r.get("term") else None] if p]
        label = " | ".join(parts) if parts else ""
        aud_lbl = {"teacher":"For teachers","student":"For students","parent":"For parents"}.get(aud,"")
        lines.append(f"{i}. {title}")
        if label:   lines.append(f"   {label}")
        if doctype: lines.append(f"   Type: {doctype}" + (f"  ({aud_lbl})" if aud_lbl else ""))
        if desc and len(desc) > 20: lines.append(f"   {desc[:120]}")
        lines.append(f"   Price: {price}")
        lines.append(f"   {url}")
        lines.append("")
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
    Find learning materials using semantic RAG + structured filters.
    Returns formatted plain-text results with real URLs from evidence.

    Retrieval states (internal, drives logging):
      - "trusted_evidence"  : Qdrant hit with real URL
      - "catalog_evidence"  : Flat-file catalog hit with real URL
      - "no_evidence"       : Both sources returned 0 results
      - "category_fallback" : No evidence; returning browse links only
    """
    ctx: Dict[str, Optional[str]] = {
        "grade": grade, "subject": subject,
        "term": term, "year": year, "audience": audience,
    }

    # Fill from history
    if history and not (ctx["grade"] and ctx["subject"]):
        from elimu_ai.tools.teacher import extract_context_from_history
        hist = extract_context_from_history(history[-6:])
        for k in ("grade", "subject", "term", "year", "audience"):
            if not ctx[k] and hist.get(k):
                ctx[k] = hist[k]

    # Fill from question
    if not (ctx["grade"] and ctx["subject"]):
        kg, ks, kt, ky = _extract_from_keyword(question)
        if not ctx["grade"]   and kg: ctx["grade"]   = kg
        if not ctx["subject"] and ks: ctx["subject"] = ks
        if not ctx["term"]    and kt: ctx["term"]    = kt
        if not ctx["year"]    and ky: ctx["year"]    = ky

    doc_type = _infer_doc_type(question)
    if not ctx["audience"]:
        ctx["audience"] = _infer_audience_from_keyword(question) or None

    logger.debug("find_materials: grade=%s subject=%s term=%s audience=%s doctype=%s",
                 ctx["grade"], ctx["subject"], ctx["term"], ctx["audience"], doc_type)

    if not ctx["subject"] and not ctx["grade"]:
        return ("I can find the exact materials for you! "
                "Could you tell me which subject and grade you need? "
                "For example: Grade 8 Mathematics, Form 3 Biology.")

    g, s, t, y, aud = ctx["grade"], ctx["subject"], ctx["term"], ctx["year"], ctx["audience"]

    # 1. Qdrant semantic search
    all_results: List[Dict[str, Any]] = []
    seen_urls: set = set()
    qdrant_count = 0

    qdrant_hits = _qdrant_search_for_query(g, s, t, y, aud, doc_type, question)
    for r in qdrant_hits:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_results.append(r)
            qdrant_count += 1

    # 2. Catalog fallback
    catalog_count = 0
    if len(all_results) < 3:
        cat_hits = _catalog_search_for_query(g, s, t, y, aud, doc_type, question)
        for r in cat_hits:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)
                catalog_count += 1

    # 3. No evidence at all — record failure and return browse fallback
    if not all_results:
        logger.info(
            "find_materials: no evidence found for question=%r grade=%s subject=%s "
            "— recording retrieval failure",
            question[:80], g, s,
        )
        _record_retrieval_failure(
            question=question,
            grade=g,
            subject=s,
            term=t,
            audience=aud,
            doc_type=doc_type,
        )
        return _category_fallback(ctx, doc_type, question)

    # 4. Rerank
    ranked = _rerank_evidence(all_results, g, s, t, aud)

    # 5. Filter teacher docs for student requests
    if aud not in ("teacher",):
        student = [r for r in ranked if r.get("audience") != "teacher"]
        if student:
            ranked = student

    top = ranked[:5]

    # 6. Build header
    header = ""
    parts = [p for p in [g, s] if p]
    if parts:
        header = f"Here are the most relevant materials for {' '.join(parts)}"
        if t:   header += f" Term {t}"
        if y:   header += f" ({y})"
        if aud: header += f" — for {aud}s"
        header += ":\n\n"

    logger.info("find_materials: returning %d results (qdrant=%d catalog=%d) for %r",
                len(top), qdrant_count, catalog_count, question[:60])
    return header + _format_evidence(top, question)


def _record_retrieval_failure(
    question: str,
    grade: Optional[str],
    subject: Optional[str],
    term: Optional[str],
    audience: Optional[str],
    doc_type: Optional[str],
) -> None:
    """
    Record a zero-evidence retrieval to ai_failed_queries.
    Non-fatal — any DB error is silently swallowed.
    The fallback response is still returned to the user.
    """
    try:
        from elimu_ai.agents.learning import LearningAgent
        LearningAgent().record_failure(
            question=question,
            intents=["librarian"],
            tools_used=["qdrant_search", "catalog_search"],
            failure_reason="no_evidence",
            confidence=0.0,
            suggested_fix=(
                f"No documents found for grade={grade} subject={subject} "
                f"term={term} audience={audience} doctype={doc_type}. "
                "Check catalog coverage and Qdrant collection health."
            ),
        )
    except Exception as exc:
        logger.debug("find_materials: could not record retrieval failure: %s", exc)


def build_librarian_prompt(question: str, catalog_results: str = "") -> str:
    return LIBRARIAN_PROMPT.format(
        context=catalog_results or "No catalog results found.",
        question=question,
    )


def get_evidence_records(
    question: str,
    grade: Optional[str] = None,
    subject: Optional[str] = None,
    term: Optional[str] = None,
    year: Optional[str] = None,
    audience: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Return structured evidence records (for Gemini context building).
    URLs come from payload only — never invented.
    """
    doc_type = _infer_doc_type(question)
    if not audience:
        audience = _infer_audience_from_keyword(question) or None

    all_results: List[Dict[str, Any]] = []
    seen: set = set()

    for r in _qdrant_search_for_query(grade, subject, term, year, audience, doc_type, question):
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url); all_results.append(r)

    if len(all_results) < limit:
        for r in _catalog_search_for_query(grade, subject, term, year, audience, doc_type, question, limit):
            url = r.get("url", "")
            if url and url not in seen:
                seen.add(url); all_results.append(r)

    ranked = _rerank_evidence(all_results, grade, subject, term, audience)
    if audience not in ("teacher",):
        student = [r for r in ranked if r.get("audience") != "teacher"]
        if student:
            ranked = student

    return ranked[:limit]
