"""Tests for individual tool functions."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))


# ── Teacher ───────────────────────────────────────────────────────────────────

from elimu_ai.tools.teacher import (
    build_teacher_prompt, extract_context_hints, extract_context_from_history
)

def test_build_teacher_prompt_contains_question():
    p = build_teacher_prompt("What is osmosis?", "some context")
    assert "osmosis" in p

def test_build_teacher_prompt_contains_context():
    p = build_teacher_prompt("test", "MY_CONTEXT_STRING")
    assert "MY_CONTEXT_STRING" in p

def test_extract_context_hints_grade():
    ctx = extract_context_hints("Grade 8 Mathematics notes")
    assert ctx["grade"] == "grade8"

def test_extract_context_hints_subject():
    ctx = extract_context_hints("Grade 8 Mathematics notes")
    assert ctx["subject"] == "mathematics"

def test_extract_context_hints_term():
    ctx = extract_context_hints("Term 2 schemes of work")
    assert ctx["term"] == "2"

def test_extract_context_hints_year():
    ctx = extract_context_hints("schemes of work 2026")
    assert ctx["year"] == "2026"

def test_extract_context_hints_form():
    ctx = extract_context_hints("Form 3 Biology notes")
    assert ctx["grade"] == "form3"

def test_extract_context_from_history():
    history = [
        {"role": "user", "content": "I study Grade 9 Biology"},
        {"role": "assistant", "content": "Great!"},
    ]
    ctx = extract_context_from_history(history)
    assert ctx["grade"] == "grade9"
    assert ctx["subject"] == "biology"

def test_extract_context_audience_teacher():
    ctx = extract_context_hints("I need scheme of work for grade 5")
    assert ctx["audience"] == "teacher"


# ── Quiz ──────────────────────────────────────────────────────────────────────

from elimu_ai.tools.quiz import build_quiz_prompt, quiz_fallback

def test_build_quiz_prompt_contains_question():
    p = build_quiz_prompt("Cell biology")
    assert "Cell biology" in p

def test_build_quiz_prompt_with_context():
    p = build_quiz_prompt("Photosynthesis", "Source content here")
    assert "Source content here" in p

def test_build_quiz_prompt_no_gemini_call():
    # build_quiz_prompt must return a string without calling Gemini
    result = build_quiz_prompt("test topic")
    assert isinstance(result, str)
    assert len(result) > 10

def test_quiz_fallback_returns_string():
    result = quiz_fallback("Grade 8 Biology")
    assert isinstance(result, str)
    assert len(result) > 0


# ── Community ─────────────────────────────────────────────────────────────────

from elimu_ai.tools.community import build_community_prompt

def test_build_community_prompt_contains_question():
    p = build_community_prompt("KCSE stress")
    assert "KCSE stress" in p

def test_build_community_prompt_with_context():
    p = build_community_prompt("CBC exams", "forum context")
    assert "forum context" in p


# ── Library ───────────────────────────────────────────────────────────────────

from elimu_ai.tools.library import find_materials, build_librarian_prompt

def test_find_materials_returns_string():
    result = find_materials("Grade 8 Mathematics notes")
    assert isinstance(result, str)
    assert len(result) > 0

def test_find_materials_no_grade_asks_clarification():
    result = find_materials("random stuff without grade or subject info xyz")
    assert isinstance(result, str)

def test_build_librarian_prompt_contains_question():
    p = build_librarian_prompt("Find chemistry notes", "catalog results here")
    assert "chemistry notes" in p
    assert "catalog results here" in p


# ── Moderation ────────────────────────────────────────────────────────────────

from elimu_ai.tools.moderation import moderate

def test_moderate_approves_clean_content():
    result = moderate("What is the best way to study for KCSE?")
    assert result == "Content approved."

def test_moderate_rejects_empty():
    result = moderate("")
    assert "rejected" in result.lower()

def test_moderate_flags_spam():
    result = moderate("buy now click here free money")
    assert "flagged" in result.lower() or "rejected" in result.lower()

def test_moderate_flags_profanity():
    result = moderate("fuck this")
    assert "approved" not in result.lower()

def test_moderate_does_not_flag_partial_word_matches():
    result = moderate("This is a skillful science lesson")
    assert result == "Content approved."

def test_moderate_rejects_too_short():
    result = moderate("hi")
    assert "rejected" in result.lower()


# ── Recommendations ───────────────────────────────────────────────────────────

from elimu_ai.tools.recommendations import recommend

def test_recommend_returns_string():
    result = recommend("Grade 6 Science notes")
    assert isinstance(result, str)
    assert len(result) > 0


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
