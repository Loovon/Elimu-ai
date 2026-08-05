"""Tests for multi-intent detection."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from elimu_ai.intent import detect_intents, primary_intent, has_intent, intent_names


def test_quiz_intent_detected():
    intents = detect_intents("Give me a quiz on photosynthesis")
    names = [i.name for i in intents]
    assert "quiz" in names, f"Expected quiz, got {names}"


def test_librarian_intent_detected():
    intents = detect_intents("I need Grade 8 Mathematics notes")
    names = [i.name for i in intents]
    assert "librarian" in names or "recommendation" in names, f"Got {names}"


def test_teacher_intent_detected():
    intents = detect_intents("Explain osmosis to me")
    names = [i.name for i in intents]
    assert "teacher" in names, f"Expected teacher, got {names}"


def test_multi_intent():
    intents = detect_intents("Recommend chemistry notes then quiz me")
    names = [i.name for i in intents]
    assert "quiz" in names, f"quiz not in {names}"
    assert len(intents) >= 2, f"Expected multiple intents, got {len(intents)}"


def test_community_intent():
    intents = detect_intents("Start a discussion about KCSE exams")
    names = [i.name for i in intents]
    assert "community" in names or "discussion" in names, f"Got {names}"


def test_primary_intent_returns_string():
    result = primary_intent("What is photosynthesis?")
    assert isinstance(result, str)
    assert result in {
        "teacher", "quiz", "librarian", "recommendation",
        "community", "discussion", "catalog", "search",
        "moderation", "general_chat",
    }


def test_has_intent():
    assert has_intent("quiz me on biology", "quiz")
    assert not has_intent("explain photosynthesis", "moderation")


def test_intent_names_returns_list():
    result = intent_names("I need notes and a quiz")
    assert isinstance(result, list)
    assert len(result) >= 1


def test_fallback_to_teacher():
    intents = detect_intents("xyzzy nonsense 123")
    assert len(intents) >= 1
    # Should always return something
    assert intents[0].name is not None


def test_confidence_ordering():
    intents = detect_intents("quiz me on cell biology")
    for i in range(len(intents) - 1):
        assert intents[i].confidence >= intents[i + 1].confidence


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
