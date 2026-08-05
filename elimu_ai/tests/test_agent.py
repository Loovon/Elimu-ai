"""Tests for the backward-compatible run_agent() API."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from elimu_ai.agent import run_agent


def test_run_agent_returns_dict():
    result = run_agent("What is photosynthesis?")
    assert isinstance(result, dict)


def test_run_agent_has_correct_keys():
    result = run_agent("Explain osmosis")
    assert "persona"  in result
    assert "answer"   in result
    assert "sources"  in result
    assert "tools"    in result


def test_run_agent_answer_is_string():
    result = run_agent("What is the water cycle?")
    assert isinstance(result["answer"], str)
    assert len(result["answer"]) > 0


def test_run_agent_tools_is_list():
    result = run_agent("explain mitosis")
    assert isinstance(result["tools"], list)


def test_run_agent_sources_is_list():
    result = run_agent("explain mitosis")
    assert isinstance(result["sources"], list)


def test_run_agent_persona_is_string():
    result = run_agent("Grade 8 maths notes")
    assert isinstance(result["persona"], str)


def test_run_agent_empty_question():
    result = run_agent("")
    assert isinstance(result["answer"], str)
    assert result["persona"] == "teacher"


def test_run_agent_with_history():
    history = [{"role": "user", "content": "I study Grade 10 Biology"}]
    result = run_agent("explain DNA replication", history=history)
    assert isinstance(result["answer"], str)


def test_run_agent_with_session_id():
    result = run_agent("hello", session_id="test-session-abc")
    assert isinstance(result, dict)


def test_run_agent_no_extra_keys():
    """API response shape must stay exactly as defined — no extra keys."""
    result = run_agent("test")
    allowed_keys = {"persona", "answer", "sources", "tools"}
    extra = set(result.keys()) - allowed_keys
    assert not extra, f"Unexpected keys in response: {extra}"


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
