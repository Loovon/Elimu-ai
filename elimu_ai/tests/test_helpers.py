"""Tests for helper utilities."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from elimu_ai.helpers import clean_answer, referral_url, rewrite_links, search_url


def test_clean_answer_strips_bold():
    assert clean_answer("**bold text**") == "bold text"

def test_clean_answer_strips_italic():
    assert clean_answer("_italic text_") == "italic text"

def test_clean_answer_strips_heading():
    result = clean_answer("## Heading\nsome text")
    assert "##" not in result
    assert "some text" in result

def test_clean_answer_strips_code_block():
    result = clean_answer("```python\ncode here\n```")
    assert "```" not in result

def test_clean_answer_empty():
    assert clean_answer("") == ""

def test_clean_answer_none_like():
    assert clean_answer(None) == ""  # type: ignore

def test_clean_answer_collapses_blank_lines():
    result = clean_answer("line1\n\n\n\n\nline2")
    assert "\n\n\n" not in result

def test_referral_url_appends_rid():
    url = referral_url("https://www.elimulibrary.com/doc/1")
    assert "rid=" in url

def test_referral_url_no_duplicate():
    url = referral_url("https://www.elimulibrary.com/doc/1?ref=elimutalks")
    # Already has ref — should not duplicate
    count = url.count("ref=elimutalks")
    assert count == 1

def test_referral_url_empty():
    assert referral_url("") == ""

def test_rewrite_links_rewrites_urls():
    text = "Check https://www.elimulibrary.com/doc/1 here"
    result = rewrite_links(text)
    assert "rid=" in result

def test_rewrite_links_empty():
    assert rewrite_links("") == ""

def test_rewrite_links_no_urls():
    text = "No URLs in this text."
    assert rewrite_links(text) == text

def test_search_url_contains_query():
    url = search_url("Grade 8 Maths")
    assert "Grade+8+Maths" in url or "Grade%208%20Maths" in url or "Grade" in url
    assert "elimulibrary.com" in url

def test_search_url_contains_ref():
    url = search_url("chemistry notes")
    assert "ref=elimutalks" in url


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
