"""Tests for the Orchestrator."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from elimu_ai.orchestrator import run_orchestrator, OrchestratorResult, _merge_outputs
from elimu_ai.intent import IntentResult


def test_returns_orchestrator_result():
    result = run_orchestrator("What is photosynthesis?")
    assert isinstance(result, OrchestratorResult)


def test_result_has_required_fields():
    result = run_orchestrator("Explain osmosis")
    assert hasattr(result, "persona")
    assert hasattr(result, "answer")
    assert hasattr(result, "sources")
    assert hasattr(result, "tools")
    assert hasattr(result, "intents")
    assert hasattr(result, "request_id")
    assert hasattr(result, "execution_ms")


def test_answer_is_non_empty_string():
    result = run_orchestrator("What is mitosis?")
    assert isinstance(result.answer, str)
    assert len(result.answer) > 0


def test_tools_list_is_not_empty():
    result = run_orchestrator("quiz me on biology")
    assert isinstance(result.tools, list)
    assert len(result.tools) >= 1


def test_sources_is_list():
    result = run_orchestrator("explain photosynthesis")
    assert isinstance(result.sources, list)


def test_intents_is_list_of_intent_results():
    result = run_orchestrator("test me on Grade 8 science")
    assert isinstance(result.intents, list)
    for i in result.intents:
        assert isinstance(i, IntentResult)


def test_persona_is_valid_string():
    valid = {"teacher", "quiz", "librarian", "recommendation",
             "community", "discussion", "catalog", "search",
             "moderation", "general_chat"}
    result = run_orchestrator("Grade 10 physics notes")
    assert result.persona in valid, f"Unexpected persona: {result.persona}"


def test_empty_question_returns_gracefully():
    result = run_orchestrator("")
    assert isinstance(result.answer, str)
    assert len(result.answer) > 0


def test_whitespace_question_returns_gracefully():
    result = run_orchestrator("   ")
    assert isinstance(result.answer, str)


def test_request_id_is_set():
    result = run_orchestrator("hello", request_id="test-req-001")
    assert result.request_id == "test-req-001"


def test_execution_ms_is_positive():
    result = run_orchestrator("explain the water cycle")
    assert result.execution_ms >= 0


def test_with_history():
    history = [
        {"role": "user",      "content": "I am studying Grade 9 Biology"},
        {"role": "assistant", "content": "Great! What would you like to know?"},
    ]
    result = run_orchestrator("explain cell division", history=history)
    assert isinstance(result.answer, str)


# ── _merge_outputs unit tests ─────────────────────────────────────────────────

def test_merge_single_output():
    outputs = {"teacher": "Photosynthesis is the process..."}
    merged = _merge_outputs(outputs, [], "test")
    assert "Photosynthesis" in merged


def test_merge_multiple_outputs_uses_labels():
    outputs = {
        "teacher": "Here is the explanation.",
        "quiz":    "1. What is photosynthesis?",
    }
    intents = [IntentResult(0.9, "teacher"), IntentResult(0.8, "quiz")]
    merged = _merge_outputs(outputs, intents, "test")
    assert "Explanation" in merged
    assert "Practice Quiz" in merged


def test_merge_empty_outputs():
    merged = _merge_outputs({}, [], "test")
    assert isinstance(merged, str)
    assert len(merged) > 0


def test_merge_strips_error_markers():
    outputs = {
        "teacher": "Photosynthesis is ...",
        "quiz":    "[quiz failed: timeout]",
    }
    merged = _merge_outputs(outputs, [], "test")
    assert "[quiz failed" not in merged


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
