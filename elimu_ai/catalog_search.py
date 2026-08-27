"""
elimu_ai/catalog_search.py

Fast search over the locally stored Elimu Library catalog index.
Index is built by:  python manage.py index_elimu_catalog

Public API:
  search_catalog(...)          → list of doc dicts
  format_recommendations(...)  → formatted plain-text string
  catalog_available()          → bool
"""

from __future__ import annotations

import json
import re
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
_INDEX_PATH   = BASE_DIR / "elimu_index.json"
_CATALOG_PATH = BASE_DIR / "elimu_catalog.json"

# ── In-memory cache ───────────────────────────────────────────────────────────

_index:   Optional[Dict] = None
_catalog: Optional[List] = None

# ── URLs ──────────────────────────────────────────────────────────────────────

BASE_SEARCH  = "https://www.elimulibrary.com/?s="
_REF_PARAM    = "ref=elimutalks"
_RETURN_PARAM = "return_url=https%3A%2F%2Felimitalks.com"

# ── Pricing ───────────────────────────────────────────────────────────────────

_PRICE_MAP = {
    "notes":       "KES 199-399",
    "schemes":     "KES 199",
    "lesson plan": "KES 199",
    "booklet":     "KES 349",
    "homework":    "KES 349",
    "designs":     "KES 199",
}
_DEFAULT_PRICE = "KES 100"

# ── Subject aliases ───────────────────────────────────────────────────────────
# Maps user-friendly / shorthand names to normalised catalog keys.

_SUBJECT_ALIASES: Dict[str, str] = {
    "maths":           "mathematics",
    "math":            "mathematics",
    "eng":             "english",
    "kisw":            "kiswahili",
    "swahili":         "kiswahili",
    "bio":             "biology",
    "chem":            "chemistry",
    "phys":            "physics",
    "hist":            "history",
    "geo":             "geography",
    "geog":            "geography",
    "bus":             "businessstudies",
    "business":        "businessstudies",
    "comp":            "computerstudies",
    "pre tech":        "pre-technicalstudies",
    "pre-tech":        "pre-technicalstudies",
    "agri":            "agricultureandnutrition",
    "agriculture":     "agricultureandnutrition",
    "social":          "socialstudies",
    "integ":           "integratedscience",
    "integrated":      "integratedscience",
    "environ":         "environmentalactivities",
    "creative":        "creativearts",
    "mathactivities":  "mathematicsactivities",
    "engactivities":   "englishactivities",
    "kiswactivities":  "kiswahiliactivities",
    "csl":             "computerstudies",
    "power mechanics": "powermechanics",
    "music":           "musicanddance",
    "music and dance": "musicanddance",
    "general science": "generalscience",
    "core maths":      "mathematics",
    "core mathematics": "mathematics",
    "essential maths": "mathematics",
    "essential mathematics": "mathematics",
}

# ── Doc-type keywords (for audience / type inference) ────────────────────────

_TEACHER_DOC_TYPES = {
    "scheme of work", "schemes of work", "lesson plan", "lesson plans",
    "record of work", "records of work", "curriculum design",
    "curriculum designs", "scheme", "sow", "rubric", "rubrics",
}

_STUDENT_DOC_TYPES = {
    "notes", "revision", "exam", "exams", "assessment", "assessment book",
    "past paper", "past papers", "topical", "homework", "booklet",
}


# ── Kenya Academic Calendar ───────────────────────────────────────────────────

def current_term() -> str:
    """Return current Kenya school term based on today's date."""
    month = _date.today().month
    if month in (1, 2, 3, 4):
        return "1"
    elif month in (5, 6, 7, 8):
        return "2"
    return "3"


def current_year() -> str:
    return str(_date.today().year)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return (s or "").lower().replace(" ", "")


def _resolve_subject(s: str) -> str:
    """Normalise a subject string to match catalog keys."""
    if not s:
        return s
    n = _norm(s)
    return _SUBJECT_ALIASES.get(n, n)


def _price(doc: Dict) -> str:
    if doc.get("price"):
        return doc["price"]
    cat = (doc.get("category") or "").lower()
    for k, v in _PRICE_MAP.items():
        if k in cat:
            return v
    return _DEFAULT_PRICE


def _score(
    doc: Dict,
    grade: Optional[str] = None,
    subject: Optional[str] = None,
    term: Optional[str] = None,
    year: Optional[str] = None,
    audience: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> int:
    """
    Relevance score for ranking. Higher = better match.
    Exact grade + subject is most important; term/year add refinement.
    Audience mismatch is penalised so students don't see teacher schemes.
    """
    score = 0
    if grade   and _norm(doc.get("grade")   or "") == _norm(grade):   score += 6
    if subject and _norm(doc.get("subject") or "") == _norm(subject): score += 6
    if term    and str(doc.get("term")   or "") == str(term):         score += 3
    if year    and str(doc.get("year")   or "") == str(year):         score += 3
    if audience and (doc.get("audience") or "") == audience:          score += 2

    # Penalise teacher-audience docs when student/unspecified is requesting
    doc_aud = doc.get("audience") or ""
    if doc_aud == "teacher" and audience in (None, "student", ""):
        score -= 4

    if doc_type and doc_type in _norm((doc.get("doctype") or "") + (doc.get("category") or "")):
        score += 2

    return score


def _load() -> None:
    """Load index and catalog from disk into module-level cache."""
    global _index, _catalog
    if _index is None and _INDEX_PATH.exists():
        try:
            _index = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            _index = {}
    if _catalog is None and _CATALOG_PATH.exists():
        try:
            _catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            _catalog = []


def _add_ref(url: str) -> str:
    """Append referral tracking to an Elimu Library URL (no-op if already present)."""
    if not url or _REF_PARAM in url:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + _REF_PARAM + "&" + _RETURN_PARAM


# ── Keyword extraction ────────────────────────────────────────────────────────

def _extract_from_keyword(keyword: str):
    """
    Pull grade, subject, term, year out of a free-text keyword string.
    Returns (grade, subject, term, year) — each may be None.
    """
    kw = keyword.lower()
    grade = subject = term = year = None

    # Grade patterns: grade 6, grade6, pp1, pp2, form 3
    m = re.search(r"grade\s*(\d+|pp1|pp2)", kw)
    if m:
        grade = f"grade{m.group(1).replace(' ', '')}"
    if not grade:
        m = re.search(r"\bpp(\d)\b", kw)
        if m:
            grade = f"gradepp{m.group(1)}"
    if not grade:
        m = re.search(r"\bform\s*(\d)\b", kw)
        if m:
            grade = f"form{m.group(1)}"

    # Term
    m = re.search(r"\bterm\s*(\d)\b", kw)
    if m:
        term = m.group(1)

    # Year
    m = re.search(r"\b(20\d{2})\b", kw)
    if m:
        year = m.group(1)

    # Subject — ordered longest first to prefer "mathematics activities" over "mathematics"
    _subjects = [
        "social studies", "integrated science", "environmental activities",
        "creative arts", "pre-technical studies", "agriculture and nutrition",
        "mathematics activities", "english activities", "kiswahili activities",
        "mathematics", "english", "kiswahili", "biology", "chemistry", "physics",
        "history", "geography", "cre", "ire", "business studies",
        "computer studies", "agriculture", "science",
        "general science", "power mechanics", "music and dance",
    ]
    for s in sorted(_subjects, key=len, reverse=True):
        if s in kw:
            subject = s.replace(" ", "")
            break

    # Aliases as fallback
    if not subject:
        for alias, canonical in _SUBJECT_ALIASES.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", kw):
                subject = canonical
                break

    return grade, subject, term, year


def _infer_audience_from_keyword(keyword: str) -> str:
    """
    Infer the likely audience from the request keywords.
    Returns "teacher", "student", "parent", or "" (unknown).
    """
    kw = keyword.lower()
    teacher_hints = {
        "scheme", "schemes", "lesson plan", "lesson plans", "sow",
        "record of work", "records of work", "curriculum design",
        "curriculum designs", "rubric", "rubrics", "i teach",
    }
    parent_hints = {"homework", "holiday homework", "my child", "for my", "parent"}
    student_hints = {"exam", "exams", "revision", "notes", "assessment", "past paper",
                     "student", "learner", "topical", "booklet"}

    if any(h in kw for h in teacher_hints):
        return "teacher"
    if any(h in kw for h in parent_hints):
        return "parent"
    if any(h in kw for h in student_hints):
        return "student"
    return ""


# ── Main search function ──────────────────────────────────────────────────────

def search_catalog(
    grade: Optional[str] = None,
    subject: Optional[str] = None,
    term: Optional[str] = None,
    year: Optional[str] = None,
    keyword: Optional[str] = None,
    audience: Optional[str] = None,
    doctype: Optional[str] = None,
    max_results: int = 5,
) -> List[Dict]:
    """
    Search the Elimu Library catalogue index.

    Returns a list of document dicts sorted by relevance score.
    Each dict contains: title, url, grade, subject, term, year,
    category, audience, doctype, description, price.
    """
    _load()
    candidates: List[Dict] = []

    g   = _norm(grade)   if grade   else ""
    s   = _resolve_subject(subject) if subject else ""
    aud = (audience or "").lower()
    dt  = _norm(doctype) if doctype else ""

    if _index:
        # ── Pass 1: Exact grade + subject + audience (most specific) ───────
        if g and s and aud:
            ga_key = f"{g}|{aud}"
            pool = _index.get("by_grade_audience", {}).get(ga_key, [])
            candidates = [d for d in pool if _norm(d.get("subject", "")) == s]

        # ── Pass 2: Grade + subject ────────────────────────────────────────
        if not candidates and g and s:
            candidates = list(_index.get("by_grade_subject", {}).get(f"{g}|{s}", []))

        # ── Pass 3: Subject across all grades ─────────────────────────────
        if not candidates and s:
            all_subj = list(_index.get("by_subject", {}).get(s, []))
            if not all_subj:
                all_subj = list(_index.get("by_subject", {}).get(_norm(subject), []))
            if all_subj and g:
                candidates = [d for d in all_subj if _norm(d.get("grade", "")) == g]
            else:
                candidates = all_subj

        # ── Pass 4: Audience + grade (teacher wanting schemes/designs) ─────
        if not candidates and aud and g:
            candidates = list(_index.get("by_grade_audience", {}).get(f"{g}|{aud}", []))

        # ── Pass 5: Audience only ──────────────────────────────────────────
        if not candidates and aud:
            candidates = list(_index.get("by_audience", {}).get(aud, []))

        # ── Pass 6: Grade only ─────────────────────────────────────────────
        if not candidates and g:
            candidates = list(_index.get("by_grade", {}).get(g, []))

        # ── Doctype filter ─────────────────────────────────────────────────
        if candidates and dt:
            dt_filtered = [
                d for d in candidates
                if dt in _norm(d.get("doctype", "")) or dt in _norm(d.get("category", ""))
            ]
            if dt_filtered:
                candidates = dt_filtered

        # ── Pass 7: Keyword — title + description full-text search ─────────
        if not candidates and keyword:
            kw = keyword.lower()
            candidates = [
                d for d in _index.get("all", [])
                if kw in (d.get("title") or "").lower()
                or kw in (d.get("description") or "").lower()
            ]

        # ── Pass 8: Keyword — extract grade/subject then retry ─────────────
        if not candidates and keyword:
            kg, ks, kt, ky = _extract_from_keyword(keyword)
            kaud = _infer_audience_from_keyword(keyword)

            if kg and ks:
                candidates = list(_index.get("by_grade_subject", {}).get(f"{kg}|{ks}", []))
            elif kg and kaud:
                candidates = list(_index.get("by_grade_audience", {}).get(f"{kg}|{kaud}", []))
            elif kg:
                candidates = list(_index.get("by_grade", {}).get(kg, []))
            elif ks:
                candidates = list(_index.get("by_subject", {}).get(ks, []))

            if kt and not term:
                term = kt
            if ky and not year:
                year = ky

    elif _catalog:
        # Fallback when index not built — linear scan of flat catalog
        kw = (keyword or "").lower()
        candidates = [
            d for d in _catalog
            if not kw
            or kw in (d.get("title") or "").lower()
            or kw in (d.get("description") or "").lower()
        ]

    # ── Post-filter by term / year ─────────────────────────────────────────
    if candidates and term:
        t_filt = [d for d in candidates if str(d.get("term", "")) == str(term)]
        if t_filt:
            candidates = t_filt

    if candidates and year:
        y_filt = [d for d in candidates if str(d.get("year", "")) == str(year)]
        if y_filt:
            candidates = y_filt

    # ── Keyword word-level relevance filter (only when we already have hits) ─
    if candidates and keyword:
        kw = keyword.lower()
        words = [w for w in kw.split() if len(w) > 3]
        if words:
            filtered = [
                d for d in candidates
                if any(
                    w in (d.get("title") or "").lower()
                    or w in (d.get("description") or "").lower()
                    for w in words
                )
            ]
            if filtered:
                candidates = filtered

    # ── Score, deduplicate, return top N ──────────────────────────────────
    scored = sorted(
        candidates,
        key=lambda d: _score(d, grade, subject, term, year, aud or None, dt or None),
        reverse=True,
    )

    seen: set = set()
    results: List[Dict] = []
    for d in scored:
        url = d.get("url", "")
        if url and url not in seen:
            seen.add(url)
            results.append(d)
        if len(results) >= max_results:
            break

    return results


# ── Formatting ────────────────────────────────────────────────────────────────

def format_recommendations(results: List[Dict], question: str = "") -> str:
    """
    Format catalog results as clean plain text suitable for the chat widget.
    Each URL goes on its own line so the front-end linkify() renders it clickable.
    """
    lines: List[str] = []

    if not results:
        lines.append("I couldn't find an exact match in the catalog.")
        lines.append("You can search directly here:")
        lines.append(f"{BASE_SEARCH}{quote(question)}&{_REF_PARAM}&{_RETURN_PARAM}")
        return "\n".join(lines)

    lines.append(
        f"Here are the best matching materials from the Elimu Library ({len(results)} found):"
    )
    lines.append("")

    for i, doc in enumerate(results, 1):
        title    = doc.get("title", "Document").title()
        url      = _add_ref(doc.get("url", ""))
        price    = doc.get("price") or _DEFAULT_PRICE
        audience = doc.get("audience", "")
        doctype  = doc.get("doctype", "")
        desc     = doc.get("description", "")

        # Metadata label
        parts = [p for p in [
            doc.get("year"),
            doc.get("grade"),
            doc.get("subject"),
            f"Term {doc['term']}" if doc.get("term") else None,
        ] if p]
        label = " | ".join(parts) if parts else ""

        # Audience indicator
        aud_label = ""
        if audience == "teacher":
            aud_label = "For teachers"
        elif audience == "student":
            aud_label = "For students"
        elif audience == "parent":
            aud_label = "For parents"

        lines.append(f"{i}. {title}")
        if label:
            lines.append(f"   {label}")
        if doctype:
            aud_str = f"  ({aud_label})" if aud_label else ""
            lines.append(f"   Type: {doctype}{aud_str}")
        if desc and len(desc) > 20:
            lines.append(f"   {desc[:120]}")
        lines.append(f"   Price: {price}")
        lines.append(f"   {url}")
        lines.append("")

    return "\n".join(lines)


# ── Catalog availability ──────────────────────────────────────────────────────

def catalog_available() -> bool:
    """Return True if either the index or flat catalog file exists on disk."""
    return _INDEX_PATH.exists() or _CATALOG_PATH.exists()
