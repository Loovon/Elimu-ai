"""Tests for the APScheduler-based scheduler."""
import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from elimu_ai.scheduler import (
    start_scheduler, shutdown_scheduler, get_status,
    run_all_tasks, _TASK_REGISTRY,
)


def test_task_registry_has_five_tasks():
    assert len(_TASK_REGISTRY) == 5


def test_task_registry_names():
    names = {name for name, _, _ in _TASK_REGISTRY}
    expected = {
        "answer_unanswered", "generate_discussions",
        "recommend_resources", "moderate_content", "catalog_sync",
    }
    assert expected == names


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
    assert len(results) == 5


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
