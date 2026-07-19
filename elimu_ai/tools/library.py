# elimu_ai/tools/library.py
# Librarian persona: pure catalog lookup — ZERO Ollama dependency.
# Returns exact /site/document/ URLs from the crawled catalogue.
# Asks clarifying questions when context is vague.

import re
import sys
from urllib.parse import quote

BASE_SEARCH = "https://www.elimulibrary.com/?s="
REF = "ref=elimutalks&return_url=https%3A%2F%2Felimitalks.com"

CATEGORY_URLS = {
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

DOC_TYPE_MAP = {
    "scheme": "scheme of work", "sow": "scheme of work",
    "lesson plan": "lesson plan", "lesson": "lesson plan",
    "notes": "notes", "note": "notes", "revision notes": "notes",
    "past paper": "assessment", "past papers": "assessment",
    "exam": "assessment", "assessment": "assessment",
    "homework": "homework", "holiday homework": "homework",
    "revision": "assessment", "topical": "assessment",
    "booklet": "homework",
}

AUDIENCE_MAP = {
    "teacher": "teacher", "teachers": "teacher",
    "student": "student", "students": "student", "learner": "student",
    "parent": "parent", "parents": "parent",
}


def _infer_doc_type(text):
    t = text.lower()
    for kw, dt in DOC_TYPE_MAP.items():
        if kw in t:
            return dt
    return "assessment"


def _infer_audience(text):
    t = text.lower()
    for kw, aud in AUDIENCE_MAP.items():
        if kw in t:
            return aud
    if any(k in t for k in ["scheme", "lesson plan", "sow", "record of work", "i teach"]):
        return "teacher"
    if any(k in t for k in ["homework", "my child", "for my"]):
        return "parent"
    return None


def recommend_materials(question, history=None, ctx_override=None):
    """
    Main librarian entry point. Pure catalog lookup — no LLM required.
    Returns exact /site/document/ links from the crawled catalogue.
    """
    from elimu_ai.tools.teacher import _extract_ctx, _needs_clarification
    from elimu_ai.catalog_search import search_catalog, format_recommendations, catalog_available

    # Use provided context (already computed with current-message-first priority)
    if ctx_override and (ctx_override.get("grade") or ctx_override.get("subject")):
        ctx = ctx_override
    else:
        # Fallback: extract from current message first, fill gaps from history
        ctx = _extract_ctx([{"content": question}])
        if history:
            hist_ctx = _extract_ctx(history[-4:])
            for field in ("grade", "subject", "term", "year"):
                if not ctx.get(field) and hist_ctx.get(field):
                    ctx[field] = hist_ctx[field]

    # Infer doc type and audience from the question
    doc_type = _infer_doc_type(question)
    audience = _infer_audience(question) or ctx.get("audience")

    # Ask for clarification only if truly nothing to work with
    if not ctx.get("subject") and not ctx.get("grade"):
        # Try to find subject in question using aliases
        from elimu_ai.catalog_search import _extract_from_keyword
        kg, ks, kt, ky = _extract_from_keyword(question)
        if ks:
            ctx["subject"] = ks
        if kg:
            ctx["grade"] = kg
        if kt and not ctx.get("term"):
            ctx["term"] = kt

    # Still nothing — ask a focused question
    if not ctx.get("subject") and not ctx.get("grade"):
        return (
            "I can find the exact materials for you! "
            "Could you tell me which subject and grade or form you need? "
            "For example: Grade 8 Mathematics, Form 3 Biology, or Grade 2 English."
        )

    if not catalog_available():
        q = " ".join(p for p in [ctx.get("grade",""), ctx.get("subject","")] if p)
        return f"Search the Elimu Library: {BASE_SEARCH}{quote(q)}&{REF}"

    # Build multiple targeted searches
    all_results = []
    seen_urls = set()

    def add_results(new):
        for r in new:
            url = r.get("url","")
            if url and "/site/document/" in url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    g = ctx.get("grade")
    s = ctx.get("subject")
    t = ctx.get("term")
    y = ctx.get("year")

    # Primary: grade + subject + audience + doc_type filter
    r1 = search_catalog(grade=g, subject=s, term=t, year=y,
                        audience=audience, doctype=doc_type, max_results=5)
    add_results(r1)

    # Secondary: grade + subject without filters
    if len(all_results) < 3 and g and s:
        r2 = search_catalog(grade=g, subject=s, term=t, year=y, max_results=5)
        add_results(r2)

    # Tertiary: subject only across all grades (if grade mismatch like biology grade 3)
    if len(all_results) < 3 and s:
        r3 = search_catalog(subject=s, audience=audience, doctype=doc_type, max_results=5)
        add_results(r3)

    # Last resort: keyword
    if len(all_results) < 2:
        r4 = search_catalog(keyword=question, max_results=5)
        add_results(r4)

    if all_results:
        # Add context header
        header = ""
        if g and s:
            header = f"Here are the most relevant {s} materials for {g}"
            if t:
                header += f" Term {t}"
            if y:
                header += f" ({y})"
            if audience:
                header += f" — for {audience}s"
            header += ":"
        return (header + "\n\n" if header else "") + format_recommendations(all_results[:5], question)

    # Nothing found — give category browse link
    return _category_fallback(ctx, doc_type, question)


def _category_fallback(ctx, doc_type, question):
    """Return category browse links when catalog search finds nothing."""
    grade_num = None
    if ctx.get("grade"):
        m = re.search(r"\d+", ctx["grade"])
        if m:
            grade_num = int(m.group())

    links = ["I couldn't find an exact match, but here are the best places to browse:"]

    if grade_num is not None:
        if grade_num <= 6:
            links.append("Primary Exams: " + CATEGORY_URLS["primary_exams"])
            links.append("Primary Notes: " + CATEGORY_URLS["primary_notes"])
        elif grade_num <= 9:
            links.append("JSS Exams: " + CATEGORY_URLS["jss_exams"])
            links.append("JSS Notes: " + CATEGORY_URLS["jss_notes"])
        else:
            links.append("Secondary Exams: " + CATEGORY_URLS["secondary_exams"])
            links.append("Secondary Notes: " + CATEGORY_URLS["secondary_notes"])

    q = " ".join(p for p in [ctx.get("grade",""), ctx.get("subject","")] if p).strip() or question
    links.append(f"Search Elimu Library: {BASE_SEARCH}{quote(q)}&ref=elimutalks")
    return "\n".join(links)
