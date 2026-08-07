"""Tests for the MemoryStore."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from elimu_ai.memory import MemoryStore, SUMMARY_AFTER_TURNS


def _fresh_store():
    return MemoryStore()


def test_add_and_get_history():
    store = _fresh_store()
    store.add_turn("s1", "user", "Hello")
    store.add_turn("s1", "assistant", "Hi there!")
    history = store.get_history("s1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello"
    assert history[1]["role"] == "assistant"


def test_get_history_respects_max_turns():
    store = _fresh_store()
    for i in range(20):
        store.add_turn("s2", "user", f"msg {i}")
    history = store.get_history("s2", max_turns=4)
    assert len(history) == 4


def test_history_returns_only_role_and_content():
    store = _fresh_store()
    store.add_turn("s3", "user", "test")
    history = store.get_history("s3")
    for turn in history:
        assert set(turn.keys()) == {"role", "content"}, f"Unexpected keys: {turn.keys()}"


def test_clear_session():
    store = _fresh_store()
    store.add_turn("s4", "user", "Hello")
    store.clear_session("s4")
    assert store.get_history("s4") == []


def test_should_summarise_false_initially():
    store = _fresh_store()
    assert not store.should_summarise("new_session")


def test_should_summarise_true_after_threshold():
    store = _fresh_store()
    for i in range(SUMMARY_AFTER_TURNS):
        store.add_turn("s5", "user" if i % 2 == 0 else "assistant", f"msg {i}")
    assert store.should_summarise("s5")


def test_session_ids_tracks_active_sessions():
    store = _fresh_store()
    store.add_turn("session_a", "user", "hi")
    store.add_turn("session_b", "user", "hello")
    ids = store.session_ids()
    assert "session_a" in ids
    assert "session_b" in ids


def test_eviction_keeps_max_in_memory():
    from elimu_ai.memory import MAX_IN_MEMORY_TURNS
    store = _fresh_store()
    for i in range(MAX_IN_MEMORY_TURNS + 10):
        store.add_turn("s6", "user", f"msg {i}")
    history = store.get_history("s6", max_turns=MAX_IN_MEMORY_TURNS + 10)
    assert len(history) <= MAX_IN_MEMORY_TURNS


def test_get_history_unknown_session():
    store = _fresh_store()
    assert store.get_history("nonexistent") == []


def test_thread_safety():
    import threading
    store = _fresh_store()
    errors = []

    def write(n):
        try:
            for i in range(50):
                store.add_turn(f"thread_{n}", "user", f"msg {i}")
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=write, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"


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
