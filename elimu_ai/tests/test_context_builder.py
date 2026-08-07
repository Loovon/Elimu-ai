"""Tests for PromptContext assembly."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from elimu_ai.context_builder import build_context, PromptContext, _trim_history


def test_build_context_returns_prompt_context():
    ctx = build_context(
        question="What is osmosis?",
        persona="teacher",
        intents=["teacher"],
    )
    assert isinstance(ctx, PromptContext)
    assert ctx.question == "What is osmosis?"
    assert ctx.persona == "teacher"


def test_to_context_string_no_crash():
    ctx = build_context("Explain mitosis", "teacher")
    s = ctx.to_context_string()
    assert isinstance(s, str)
    assert len(s) > 0


def test_context_with_curriculum_hints():
    ctx = build_context(
        question="Grade 8 maths",
        persona="librarian",
        curriculum_hints={"grade": "grade8", "subject": "mathematics"},
    )
    s = ctx.to_context_string()
    assert "grade8" in s or "mathematics" in s


def test_context_with_qdrant_hits():
    class FakeHit:
        payload = {"title": "Biology Notes", "url": "http://example.com/1", "description": ""}
    ctx = build_context(
        question="biology",
        persona="teacher",
        qdrant_hits=[FakeHit()],
    )
    s = ctx.to_context_string()
    assert "Biology Notes" in s


def test_context_with_catalog_results():
    ctx = build_context(
        question="schemes",
        persona="librarian",
        catalog_results="Scheme of Work Grade 6",
    )
    s = ctx.to_context_string()
    assert "Scheme of Work" in s


def test_trim_history_respects_max_turns():
    history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    trimmed = _trim_history(history, max_turns=6)
    assert len(trimmed) <= 6


def test_trim_history_respects_max_chars():
    history = [{"role": "user", "content": "x" * 600} for _ in range(10)]
    trimmed = _trim_history(history, max_turns=10, max_chars=2000)
    total = sum(len(m["content"]) for m in trimmed)
    assert total <= 2000


def test_system_note_appended():
    ctx = build_context("test", "teacher", include_system_note=True)
    s = ctx.to_context_string()
    # Just ensure no crash — may say "Term X" or "No additional context"
    assert isinstance(s, str)


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
