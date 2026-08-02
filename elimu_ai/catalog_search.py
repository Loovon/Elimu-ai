# elimu_ai/catalog_search.py
# Fast search over the locally stored Elimu Library catalog index.
# Built by: python config/crawl_elimu_library.py + python manage.py index_elimu_catalog


import json, re, pathlib, sys
from datetime import date as _date

# ── Kenya Academic Calendar ───────────────────────────────────────────────────
def current_term() -> str:
    """Return current Kenya school term based on today's date."""
    today = _date.today()
    month = today.month
    if month in (1, 2, 3, 4):
        return "1"
    elif month in (5, 6, 7, 8):
        return "2"
    else:
        return "3"

def current_year() -> str:
    return str(_date.today().year)



from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

INDEX_PATH = BASE_DIR / "elimu_index.json"

_CATALOG_PATH = BASE_DIR / "elimu_catalog.json"
_index   = None
_catalog = None

BASE_SEARCH = "https://www.elimulibrary.com/?s="

# Default prices by category type
_PRICE_MAP = {
    "notes": "KES 199-399",
    "schemes": "KES 199",
    "lesson plan": "KES 199",
    "booklet": "KES 349",
    "homework": "KES 349",
    "designs": "KES 199",
}
_DEFAULT_PRICE = "KES 100"

# Subject aliases — maps user-friendly names to catalog-stored names
_SUBJECT_ALIASES = {
    "maths":              "mathematics",
    "math":               "mathematics",
    "eng":                "english",
    "kisw":               "kiswahili",
    "swahili":            "kiswahili",
    "bio":                "biology",
    "chem":               "chemistry",
    "phys":               "physics",
    "hist":               "history",
    "geo":                "geography",
    "geog":               "geography",
    "bus":                "businessstudies",
    "business":           "businessstudies",
    "comp":               "computerstudies",
    "pre tech":           "pre-technicalstudies",
    "pre-tech":           "pre-technicalstudies",
    "agri":               "agricultureandnutrition",
    "agriculture":        "agricultureandnutrition",
    "social":             "socialstudies",
    "integ":              "integratedscience",
    "integrated":         "integratedscience",
    "environ":            "environmentalactivities",
    "creative":           "creativearts",
    "mathactivities":     "mathematicsactivities",
    "engactivities":      "englishactivities",
    "kiswactivities":     "kiswahiliactivities",
}

def _resolve_subject(s):
    """Normalise a subject string to match catalog keys."""
    if not s:
        return s
    n = _norm(s)
    return _SUBJECT_ALIASES.get(n, n)

def _load():
    global _index, _catalog
    if _index is None and _INDEX_PATH.exists():
        _index = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    if _catalog is None and _CATALOG_PATH.exists():
        _catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))

def _norm(s):
    return (s or "").lower().replace(" ", "")

def _price(doc):
    if doc.get("price"):
        return doc["price"]
    cat = (doc.get("category") or "").lower()
    for k, v in _PRICE_MAP.items():
        if k in cat:
            return v
    return _DEFAULT_PRICE

def _score(doc, grade=None, subject=None, term=None, year=None):
    score = 0
    if grade   and _norm(doc.get("grade"))   == _norm(grade):   score += 4
    if subject and _norm(doc.get("subject")) == _norm(subject): score += 4
    if term    and str(doc.get("term"))      == str(term):      score += 2
    if year    and str(doc.get("year"))      == str(year):      score += 2
    return score

def _extract_from_keyword(keyword):
    """Pull grade and subject out of a free-text keyword string."""
    kw = keyword.lower()
    grade = None; subject = None; term = None; year = None

    m = re.search(r"grade\s*(\d+|pp1|pp2)", kw)
    if m:
        grade = f"grade{m.group(1)}"
    m = re.search(r"form\s*(\d)", kw)
    if m and not grade:
        grade = f"form{m.group(1)}"
    m = re.search(r"term\s*(\d)", kw)
    if m:
        term = m.group(1)
    m = re.search(r"\b(20\d{2})\b", kw)
    if m:
        year = m.group(1)

    subjects = [
        "social studies", "integrated science", "environmental activities",
        "creative arts", "pre-technical studies", "agriculture and nutrition",
        "mathematics activities", "mathematics", "english activities", "english",
        "kiswahili activities", "kiswahili", "biology", "chemistry", "physics",
        "history", "geography", "cre", "ire", "business studies",
        "computer studies", "agriculture", "science",
    ]
    for s in subjects:
        if s in kw:
            subject = s.replace(" ", "")
            break

    # If no subject found, check aliases (maths, bio, chem, etc.)
    if not subject:
        for alias, canonical in _SUBJECT_ALIASES.items():
            # Match alias as a whole word
            if re.search(r"\b" + re.escape(alias) + r"\b", kw):
                subject = canonical
                break

    return grade, subject, term, year

def search_catalog(grade=None, subject=None, term=None, year=None,
                   keyword=None, audience=None, doctype=None,
                   max_results=5):
    """
    Search the Elimu Library catalogue index.

    Args:
        grade:    "Grade 2", "Form 3", "PP1" etc.
        subject:  "Mathematics", "Biology" etc.
        term:     "1", "2", "3"
        year:     "2026" etc.
        keyword:  free-text keyword fallback
        audience: "teacher", "student", "parent"
        doctype:  "Scheme of Work", "Assessment", "Notes" etc.
        max_results: max docs to return

    Returns list of dicts with title, url, grade, subject, term, year,
    category, audience, doctype, description, price.
    """
    _load()
    candidates = []

    g = _resolve_subject(grade) if grade else ""
    # Don't resolve grade — grade is already normalised; resolve subject
    g = _norm(grade) if grade else ""
    s = _resolve_subject(subject) if subject else ""
    aud = (audience or "").lower()
    dt  = (doctype  or "").lower().replace(" ", "")

    if _index:
        # 1. Exact grade + subject + audience (most specific)
        if g and s and aud:
            # grade+audience first
            ga_key = f"{g}|{aud}"
            pool = _index.get("by_grade_audience", {}).get(ga_key, [])
            candidates = [d for d in pool if _norm(d.get("subject","")) == s]

        # 2. Grade + subject
        if not candidates and g and s:
            candidates = list(_index.get("by_grade_subject", {}).get(f"{g}|{s}", []))

        # 3. Subject only (across all grades) — use audience to filter
        if not candidates and s:
            all_subj = list(_index.get("by_subject", {}).get(s, []))
            if not all_subj:
                s_raw = _norm(subject) if subject else s
                all_subj = list(_index.get("by_subject", {}).get(s_raw, []))
            # Filter by grade if we have one
            if all_subj and g:
                grade_filtered = [d for d in all_subj if _norm(d.get("grade","")) == g]
                candidates = grade_filtered if grade_filtered else all_subj
            else:
                candidates = all_subj

        # 4. Audience + grade (teacher looking for schemes etc.)
        if not candidates and aud and g:
            candidates = list(_index.get("by_grade_audience", {}).get(f"{g}|{aud}", []))

        # 5. Audience only
        if not candidates and aud:
            candidates = list(_index.get("by_audience", {}).get(aud, []))

        # 6. Grade only — last resort (mixed subjects)
        if not candidates and g:
            candidates = list(_index.get("by_grade", {}).get(g, []))

        # 7. Doctype filter
        if candidates and dt:
            dt_filtered = [d for d in candidates
                           if dt in _norm(d.get("doctype","")) or
                              dt in _norm(d.get("category",""))]
            if dt_filtered:
                candidates = dt_filtered

        # 8. Keyword: title + description search
        if not candidates and keyword:
            kw = keyword.lower()
            candidates = [
                d for d in _index.get("all", [])
                if kw in (d.get("title") or "").lower()
                or kw in (d.get("description") or "").lower()
            ]

        # 9. Extract grade/subject/audience from keyword and retry
        if not candidates and keyword:
            kg, ks, kt, ky = _extract_from_keyword(keyword)
            # Also extract audience from keyword
            kaud = ""
            kw_l = keyword.lower()
            if "teacher" in kw_l or "scheme" in kw_l or "lesson plan" in kw_l:
                kaud = "teacher"
            elif "parent" in kw_l or "homework" in kw_l:
                kaud = "parent"
            elif "student" in kw_l or "exam" in kw_l or "revision" in kw_l:
                kaud = "student"

            if kg and ks:
                candidates = _index.get("by_grade_subject", {}).get(f"{kg}|{ks}", [])
            elif kg and kaud:
                candidates = _index.get("by_grade_audience", {}).get(f"{kg}|{kaud}", [])
            elif kg:
                candidates = _index.get("by_grade", {}).get(kg, [])
            elif ks:
                candidates = _index.get("by_subject", {}).get(ks, [])
            if kt and not term: term = kt
            if ky and not year: year = ky

    elif _catalog:
        kw = (keyword or "").lower()
        candidates = [d for d in _catalog
                      if not kw or kw in (d.get("title") or "").lower()
                      or kw in (d.get("description") or "").lower()]

    # Filter by term/year if provided
    if candidates and term:
        t_filt = [d for d in candidates if str(d.get("term","")) == str(term)]
        if t_filt:
            candidates = t_filt

    if candidates and year:
        y_filt = [d for d in candidates if str(d.get("year","")) == str(year)]
        if y_filt:
            candidates = y_filt

    # Apply keyword filter if we have candidates
    if candidates and keyword:
        kw = keyword.lower()
        filtered = [d for d in candidates
                    if any(w in (d.get("title") or "").lower()
                           or w in (d.get("description") or "").lower()
                           for w in kw.split() if len(w) > 3)]
        if filtered:
            candidates = filtered

    # Score, deduplicate, return top N
    scored = sorted(
        candidates,
        key=lambda d: _score(d, grade, subject, term, year),
        reverse=True
    )
    seen = set()
    results = []
    for d in scored:
        url = d.get("url", "")
        if url and url not in seen:
            seen.add(url)
            results.append(d)
        if len(results) >= max_results:
            break

    return results


# Referral constants (used by _add_ref for URLs not from catalogue)
_REF_PARAM    = "ref=elimutalks"
_RETURN_PARAM = "return_url=https%3A%2F%2Felimitalks.com"

def _add_ref(url: str) -> str:
    """
    Append referral tracking to an Elimu Library URL.
    Catalogue URLs already have ref=elimutalks — this is a no-op for those.
    """
    if not url or _REF_PARAM in url:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + _REF_PARAM + "&" + _RETURN_PARAM

def format_recommendations(results, question=""):
    """
    Format catalog results as clean plain text for the chat widget.
    Each URL goes on its own line so linkify() makes it clickable.
    No M-Pesa text — payment is handled on ElimuTalks.
    """
    from urllib.parse import quote
    lines = []

    if not results:
        lines.append("I couldn't find an exact match in the catalog.")
        lines.append("You can search directly here:")
        lines.append(f"{BASE_SEARCH}{quote(question)}&{_REF_PARAM}&{_RETURN_PARAM}")
        return "\n".join(lines)

    lines.append(f"Here are the best matching materials from the Elimu Library ({len(results)} found):")
    lines.append("")

    for i, doc in enumerate(results, 1):
        title    = doc.get("title", "Document").title()
        url      = _add_ref(doc.get("url", ""))
        price    = doc.get("price") or "KES 100"
        audience = doc.get("audience", "")
        doctype  = doc.get("doctype", "")
        desc     = doc.get("description", "")

        # Grade / subject / term / year label
        parts = [p for p in [
            doc.get("year"),
            doc.get("grade"),
            doc.get("subject"),
            f"Term {doc['term']}" if doc.get("term") else None,
        ] if p]
        label = " | ".join(parts) if parts else ""

        # Audience pill
        aud_pill = ""
        if audience == "teacher":
            aud_pill = "👩‍🏫 For teachers"
        elif audience == "student":
            aud_pill = "🎓 For students"
        elif audience == "parent":
            aud_pill = "👨‍👩‍👧 For parents"

        lines.append(f"{i}. {title}")
        if label:
            lines.append(f"   {label}")
        if doctype:
            lines.append(f"   Type: {doctype}  {aud_pill}")
        if desc and len(desc) > 20:
            lines.append(f"   {desc[:120]}")
        lines.append(f"   Price: {price}")
        lines.append(f"   {url}")
        lines.append("")

    return "\n".join(lines)


def catalog_available():
    """True if catalog or index has been built."""
    return _INDEX_PATH.exists() or _CATALOG_PATH.exists()
