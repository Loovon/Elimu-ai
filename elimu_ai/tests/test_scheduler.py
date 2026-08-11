"""Tests for the APScheduler-based scheduler."""
import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from elimu_ai.scheduler import (
    start_scheduler, shutdown_scheduler, get_status,
    run_all_tasks, _TASK_REGISTRY,
)


def test_task_registry_has_five_tasks():
    # Registry now has 10 tasks (expanded with health, memory, quiz-of-day, etc.)
    assert len(_TASK_REGISTRY) >= 5


def test_task_registry_names():
    names = {name for name, _, _ in _TASK_REGISTRY}
    expected = {
        "answer_unanswered", "generate_discussions",
        "recommend_resources", "moderate_content", "catalog_sync",
    }
    assert expected.issubset(names)


def test_scheduler_starts_and_stops():
    sched = start_scheduler(daemon=True)
    time.sleep(0.3)
    st = get_status()
    assert st["running"] is True
    assert st["started_at"] is not None
    shutdown_scheduler(wait=False)
    time.sleep(0.2)
    st2 = get_status()
    assert st2["running"] is False


def test_run_all_tasks_returns_dict():
    results = run_all_tasks()
    assert isinstance(results, dict)
    assert len(results) >= 5


def test_run_all_tasks_all_present():
    results = run_all_tasks()
    for name in ("answer_unanswered", "generate_discussions",
                 "recommend_resources", "moderate_content", "catalog_sync"):
        assert name in results, f"Missing task result: {name}"


def test_run_all_tasks_each_result_is_string():
    results = run_all_tasks()
    for name, result in results.items():
        assert isinstance(result, str), f"{name}: expected str, got {type(result)}"


def test_get_status_shape():
    st = get_status()
    assert "running"    in st
    assert "started_at" in st
    assert "last_run"   in st
    assert "errors"     in st


def test_double_start_is_safe():
    sched1 = start_scheduler(daemon=True)
    sched2 = start_scheduler(daemon=True)
    assert sched1 is sched2
    shutdown_scheduler(wait=False)


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


# ── Proactive community discussion tests ──────────────────────────────────────

from unittest.mock import patch, MagicMock


def _make_repo(
    today_count=0,
    seconds_since_last=None,
    persona_seconds=None,
    recent_topics=None,
):
    """Build a mock ProactiveDiscussionRepository for tests."""
    repo = MagicMock()
    repo.count_today_safe.return_value = today_count
    repo.seconds_since_last_safe.return_value = seconds_since_last
    repo.seconds_since_persona_last_posted_safe.return_value = persona_seconds
    repo.get_recent_topics_safe.return_value = recent_topics or []
    repo.log_discussion.return_value = None
    return repo


def test_mode1_unanswered_thread_existing_workflow():
    """Test 1: unanswered thread exists → existing workflow, no proactive discussion."""
    from elimu_ai.scheduler import task_generate_discussions

    threads = [{"id": 1, "title": "Help", "post_count": 1}]
    with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=threads), \
         patch("elimu_ai.tools.answer.answer_unanswered_threads", return_value=1) as mock_ans, \
         patch("elimu_ai.scheduler._get_proactive_repo") as mock_repo:
        result = task_generate_discussions()
    mock_ans.assert_called_once()
    mock_repo.assert_not_called()
    assert "answered_existing_thread" in result


def test_mode2_no_threads_proactive_creation():
    """Test 2: no unanswered threads → persona selected, topic chosen, create_discussion called."""
    from elimu_ai.scheduler import task_generate_discussions

    repo = _make_repo(today_count=0, seconds_since_last=99999)
    with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=[]), \
         patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
         patch("elimu_ai.scheduler._create_discussion_as_persona",
               return_value="created: /thread/test-slug/") as mock_create:
        result = task_generate_discussions()

    mock_create.assert_called_once()
    assert "created_proactive_discussion" in result


def test_mode2_cooldown_active():
    """Test 3: cooldown active → no discussion created."""
    from elimu_ai.scheduler import task_generate_discussions

    repo = _make_repo(today_count=0, seconds_since_last=100)  # 100s < 14400s cooldown
    with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=[]), \
         patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
         patch("elimu_ai.scheduler._create_discussion_as_persona") as mock_create:
        result = task_generate_discussions()

    mock_create.assert_not_called()
    assert "skipped_cooldown" in result


def test_mode2_daily_limit_reached():
    """Test 3b: daily limit reached → no discussion created."""
    from elimu_ai.scheduler import task_generate_discussions

    repo = _make_repo(today_count=99, seconds_since_last=99999)
    with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=[]), \
         patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
         patch("elimu_ai.scheduler._create_discussion_as_persona") as mock_create:
        result = task_generate_discussions()

    mock_create.assert_not_called()
    assert "skipped_cooldown" in result


def test_mode2_duplicate_topic():
    """Test 4: all topics are duplicates → no discussion created."""
    from elimu_ai.scheduler import task_generate_discussions, _PERSONA_TOPIC_POOLS

    # Fill recent_topics with ALL possible topics to force duplicate detection
    all_topics = []
    for pool in _PERSONA_TOPIC_POOLS.values():
        all_topics.extend(pool)

    repo = _make_repo(today_count=0, seconds_since_last=99999, recent_topics=all_topics)
    with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=[]), \
         patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
         patch("elimu_ai.scheduler._create_discussion_as_persona") as mock_create:
        result = task_generate_discussions()

    mock_create.assert_not_called()
    assert "skipped_duplicate" in result


def test_mode2_successful_creation_logs_correct_status():
    """Test 5: successful proactive creation → result contains created_proactive_discussion."""
    from elimu_ai.scheduler import task_generate_discussions

    repo = _make_repo(today_count=0, seconds_since_last=99999)
    with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=[]), \
         patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
         patch("elimu_ai.scheduler._create_discussion_as_persona",
               return_value="created: /thread/slug/"):
        result = task_generate_discussions()

    assert "created_proactive_discussion" in result
    # Repository should have been called to log the result
    repo.log_discussion.assert_called_once()
    log_call_kwargs = repo.log_discussion.call_args[1]
    assert log_call_kwargs.get("status") == "created_proactive_discussion"


def test_mode2_forum_api_failure_worker_stays_alive():
    """Test 6: forum API failure → error logged, function returns string (no exception)."""
    from elimu_ai.scheduler import task_generate_discussions

    repo = _make_repo(today_count=0, seconds_since_last=99999)
    with patch("elimu_ai.tools.forum.get_unanswered_threads", return_value=[]), \
         patch("elimu_ai.scheduler._get_proactive_repo", return_value=repo), \
         patch("elimu_ai.scheduler._create_discussion_as_persona",
               side_effect=Exception("Django API down")):
        try:
            result = task_generate_discussions()
        except Exception:
            assert False, "task_generate_discussions raised — worker would crash"

    assert isinstance(result, str)
    # Should log failure, not success
    repo.log_discussion.assert_called()
    logged_status = repo.log_discussion.call_args[1].get("status")
    assert logged_status == "failed"


def test_mode2_persona_rotation():
    """Test 7: repeated proactive runs select different personas."""
    from elimu_ai.scheduler import _select_persona

    selected = set()
    for day_offset in range(7):
        repo = MagicMock()
        repo.seconds_since_persona_last_posted_safe.return_value = 99999
        # Simulate different days by mocking datetime
        fake_dt = MagicMock()
        fake_dt.timetuple.return_value = MagicMock(tm_yday=day_offset + 1)
        with patch("elimu_ai.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_dt
            pname, _ = _select_persona(repo, persona_cooldown=1)
        selected.add(pname)

    # Over 7 different day offsets we should see at least 2 different personas
    assert len(selected) >= 2, f"Persona rotation failed — only got: {selected}"
