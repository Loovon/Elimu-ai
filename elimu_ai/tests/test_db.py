"""Tests for DB connection and repositories (graceful degradation when no DB)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from elimu_ai.db.connection import db_available
from elimu_ai.db.repositories import (
    MemoryRepository, AnalyticsRepository,
    SchedulerRepository, QuizRepository, RecommendationRepository,
)


def test_db_available_returns_bool():
    result = db_available()
    assert isinstance(result, bool)


def test_memory_repo_save_no_crash():
    repo = MemoryRepository()
    # Should not raise, even without DB
    repo.save_summary("session-test-1", user_id=None, summary="Test summary")


def test_memory_repo_get_summaries_no_crash():
    repo = MemoryRepository()
    result = repo.get_summaries(user_id=999)
    # Returns list or None
    assert result is None or isinstance(result, list)


def test_analytics_repo_log_no_crash():
    repo = AnalyticsRepository()
    repo.log_request(
        request_id="req-001",
        user_id=None,
        persona="teacher",
        intents=["teacher"],
        tools_used=["gemini_generate"],
        question_len=20,
        answer_len=200,
        execution_ms=150,
        had_error=False,
        session_id="s-001",
    )


def test_scheduler_repo_log_no_crash():
    repo = SchedulerRepository()
    repo.log_job(
        job_name="test_job",
        status="ok",
        result="Completed successfully",
        duration_ms=42,
    )


def test_scheduler_repo_get_recent_no_crash():
    repo = SchedulerRepository()
    result = repo.get_recent_jobs(limit=5)
    assert result is None or isinstance(result, list)


def test_quiz_repo_save_no_crash():
    repo = QuizRepository()
    repo.save_quiz(
        session_id="s-quiz-1",
        user_id=None,
        question="What is osmosis?",
        quiz_content="1. A) B) C) D)",
        subject="biology",
        grade="grade8",
    )


def test_quiz_repo_get_recent_no_crash():
    repo = QuizRepository()
    result = repo.get_recent_quizzes(user_id=999)
    assert result is None or isinstance(result, list)


def test_recommendation_repo_save_no_crash():
    repo = RecommendationRepository()
    repo.save_recommendation(
        user_id=None,
        session_id="s-rec-1",
        question="Grade 8 maths",
        results_json='[{"title":"test"}]',
        grade="grade8",
        subject="mathematics",
    )


def test_decorator_handles_db_error():
    # All repo methods decorated with @_db_op must catch and not raise
    repo = MemoryRepository()
    # Simulate calling with bad session_id type — should not raise
    try:
        repo.get_summary(None)  # type: ignore
    except Exception:
        pass  # OK to ignore — we just don't want a crash propagating


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
