"""Tests for the health check system."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from elimu_ai.health import get_health


def test_get_health_returns_dict():
    h = get_health()
    assert isinstance(h, dict)


def test_get_health_has_status():
    h = get_health()
    assert "status" in h
    assert h["status"] in ("ok", "degraded")


def test_get_health_has_all_components():
    h = get_health()
    required = {"gemini", "qdrant", "postgresql", "catalog",
                "scheduler", "memory", "agent_manager", "environment",
                "version", "uptime_seconds"}
    missing = required - set(h.keys())
    assert not missing, f"Missing health keys: {missing}"


def test_each_component_has_status():
    h = get_health()
    for key in ("gemini", "qdrant", "catalog", "scheduler", "memory", "environment"):
        assert "status" in h[key], f"No 'status' in {key}: {h[key]}"
        assert h[key]["status"] in ("ok", "degraded"), f"Bad status for {key}"


def test_uptime_is_positive():
    h = get_health()
    assert h["uptime_seconds"] >= 0


def test_version_is_string():
    h = get_health()
    assert isinstance(h["version"], str)
    assert len(h["version"]) > 0


def test_environment_lists_missing_required():
    h = get_health()
    env = h["environment"]
    assert "missing_required" in env
    assert isinstance(env["missing_required"], list)


def test_no_crash_when_services_down():
    # Should return degraded, not raise
    h = get_health()
    assert isinstance(h, dict)


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
