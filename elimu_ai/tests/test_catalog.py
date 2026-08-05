"""Tests for catalog search and formatting."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from elimu_ai.catalog_search import (
    search_catalog, format_recommendations, catalog_available,
    _extract_from_keyword, _infer_audience_from_keyword,
    _norm, _resolve_subject, _score, current_term, current_year,
)


def test_current_term_is_valid():
    term = current_term()
    assert term in ("1", "2", "3")


def test_current_year_is_reasonable():
    year = current_year()
    assert year.startswith("20")
    assert len(year) == 4


def test_norm():
    assert _norm("Mathematics") == "mathematics"
    assert _norm("Social Studies") == "socialstudies"
    assert _norm("") == ""


def test_resolve_subject_alias():
    assert _resolve_subject("maths") == "mathematics"
    assert _resolve_subject("bio") == "biology"
    assert _resolve_subject("chem") == "chemistry"


def test_extract_from_keyword_grade():
    grade, subject, term, year = _extract_from_keyword("grade 8 mathematics term 2")
    assert grade == "grade8"
    assert subject == "mathematics"
    assert term == "2"


def test_extract_from_keyword_form():
    grade, subject, term, year = _extract_from_keyword("form 3 biology")
    assert grade == "form3"
    assert subject == "biology"


def test_extract_from_keyword_pp():
    grade, subject, term, year = _extract_from_keyword("pp2 schemes of work")
    assert grade is not None
    assert "pp" in (grade or "")


def test_extract_from_keyword_year():
    grade, subject, term, year = _extract_from_keyword("grade 9 science 2026")
    assert year == "2026"


def test_infer_audience_teacher():
    assert _infer_audience_from_keyword("scheme of work grade 4") == "teacher"
    assert _infer_audience_from_keyword("lesson plan term 2")     == "teacher"


def test_infer_audience_student():
    assert _infer_audience_from_keyword("revision notes grade 8") == "student"
    assert _infer_audience_from_keyword("exam papers form 3")     == "student"


def test_infer_audience_parent():
    assert _infer_audience_from_keyword("holiday homework pp2") == "parent"


def test_score_exact_match():
    doc = {"grade": "grade8", "subject": "mathematics", "term": "2", "year": "2026", "audience": "student"}
    s = _score(doc, "grade8", "mathematics", "2", "2026", "student")
    assert s > 10


def test_score_teacher_penalty_for_student():
    doc = {"grade": "grade8", "subject": "mathematics", "audience": "teacher"}
    s = _score(doc, "grade8", "mathematics", audience="student")
    # Should be penalised
    assert s < 10


def test_catalog_available_returns_bool():
    result = catalog_available()
    assert isinstance(result, bool)


def test_search_catalog_returns_list():
    results = search_catalog(keyword="grade 8 mathematics", max_results=3)
    assert isinstance(results, list)


def test_search_catalog_results_have_url():
    results = search_catalog(keyword="schemes of work", max_results=2)
    for doc in results:
        if doc:
            assert "url" in doc


def test_format_recommendations_empty():
    text = format_recommendations([], "test query")
    assert isinstance(text, str)
    assert len(text) > 0
    assert "couldn't find" in text.lower() or "search" in text.lower()


def test_format_recommendations_with_results():
    fake_results = [{
        "title": "Grade 8 Mathematics Notes",
        "url": "https://www.elimulibrary.com/site/document/123",
        "price": "KES 199",
        "grade": "grade8",
        "subject": "mathematics",
        "term": "2",
        "year": "2026",
        "audience": "student",
        "doctype": "Notes",
        "description": "Comprehensive grade 8 mathematics notes",
    }]
    text = format_recommendations(fake_results, "grade 8 maths")
    assert "Grade 8 Mathematics Notes" in text
    assert "KES 199" in text
    assert "elimulibrary.com" in text


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
