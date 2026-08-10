"""
elimu_ai/agent_manager.py

Background Agent Manager — completely independent of Django.
Communicates with Django through ElimuAPIClient only.
Surviving a Django outage is a primary design requirement.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Shared status ─────────────────────────────────────────────────────────────
agent_manager_status: Dict[str, Any] = {
    "running":         False,
    "started_at":      None,
    "last_check_at":   None,
    "last_success_at": None,
    "last_error_at":   None,
    "observations":    [],
    "errors":          [],
    "jobs_launched":   0,
    "django_status":   "unknown",
    "catalog_status":  "unknown",
    "scheduler_status":"unknown",
    "qdrant_status":   "unknown",
    "gemini_status":   "unknown",
}

_CHECK_INTERVAL  = 60
_MAX_OBS_HISTORY = 20
_MAX_ERR_HISTORY = 10

_stop_event     = threading.Event()
_obs_lock       = threading.Lock()   # prevent overlapping cycles
_manager_thread: Optional[threading.Thread] = None


# ── Individual observations (each isolated — never crashes the loop) ──────────

def _observe_django() -> str:
    """Check Django API reachability via HTTP."""
    try:
        from elimu_ai.tools.forum import check_django_available
        ok = check_django_available()
        status = "ok" if ok else "unavailable"
        agent_manager_status["django_status"] = status
        return status
    except Exception as exc:
        agent_manager_status["django_status"] = "error"
        return f"error: {exc}"


def _observe_unanswered_threads() -> str:
    """If Django is reachable, trigger answer task for waiting threads."""
    if agent_manager_status.get("django_status") not in ("ok",):
        return "skipped_django_unavailable"
    try:
        from elimu_ai.tools.forum import get_unanswered_threads
        threads = get_unanswered_threads(cutoff_hours=3)
        count = len(threads)
        if count > 0:
            from elimu_ai.scheduler import task_answer_unanswered
            task_answer_unanswered()
            agent_manager_status["jobs_launched"] += 1
            return f"triggered_answer_{count}_threads"
        return "no_unanswered_threads"
    except Exception as exc:
        logger.warning("agent_manager: unanswered thread check failed: %s", exc)
        return f"error: {exc}"


def _observe_catalog_freshness() -> str:
    """
    Catalog state machine — prevents duplicate sync launches.
    States: fresh | stale | missing | syncing | sync_failed
    """
    try:
        from elimu_ai.catalog_search import catalog_available, _INDEX_PATH
        import pathlib, os

        if not catalog_available():
            agent_manager_status["catalog_status"] = "missing"
            return "catalog_missing"

        path = pathlib.Path(str(_INDEX_PATH))
        if not path.exists():
            agent_manager_status["catalog_status"] = "missing"
            return "catalog_missing"

        age_hours = (time.time() - os.path.getmtime(str(path))) / 3600
        if age_hours <= 24:
            agent_manager_status["catalog_status"] = "fresh"
            return "catalog_fresh"

        # Stale — trigger sync but only if not already syncing
        current = agent_manager_status.get("catalog_status", "")
        if current == "syncing":
            return "catalog_sync_in_progress"

        agent_manager_status["catalog_status"] = "syncing"
        from elimu_ai.scheduler import task_catalog_sync
        result = task_catalog_sync()
        if "Error" in result:
            agent_manager_status["catalog_status"] = "sync_failed"
            return f"catalog_sync_failed: {result}"
        agent_manager_status["catalog_status"] = "fresh"
        agent_manager_status["jobs_launched"] += 1
        return f"catalog_synced (was {age_hours:.0f}h old)"
    except Exception as exc:
        agent_manager_status["catalog_status"] = "error"
        logger.warning("agent_manager: catalog check failed: %s", exc)
        return f"error: {exc}"


def _observe_scheduler_health() -> str:
    try:
        from elimu_ai.scheduler import get_status, start_scheduler
        st = get_status()
        if not st.get("running"):
            logger.warning("agent_manager: scheduler stopped — restarting")
            start_scheduler(daemon=True)
            agent_manager_status["jobs_launched"] += 1
            agent_manager_status["scheduler_status"] = "restarted"
            return "scheduler_restarted"
        errors = st.get("errors", {})
        status = "healthy" if not errors else f"running_with_{len(errors)}_errors"
        agent_manager_status["scheduler_status"] = status
        return f"scheduler_{status}"
    except Exception as exc:
        agent_manager_status["scheduler_status"] = "error"
        logger.warning("agent_manager: scheduler health check failed: %s", exc)
        return f"error: {exc}"


def _observe_qdrant() -> str:
    try:
        from elimu_ai.qdrant_db import _get_client
        ok = _get_client() is not None
        status = "ok" if ok else "unavailable"
        agent_manager_status["qdrant_status"] = status
        return status
    except Exception as exc:
        agent_manager_status["qdrant_status"] = "error"
        return f"error: {exc}"


def _observe_gemini() -> str:
    try:
        from elimu_ai.gemini import _get_client
        ok = _get_client() is not None
        status = "ok" if ok else "unavailable"
        agent_manager_status["gemini_status"] = status
        return status
    except Exception as exc:
        agent_manager_status["gemini_status"] = "error"
        return f"error: {exc}"


def _observe_memory_summaries() -> str:
    try:
        from elimu_ai.memory import memory_store
        summarised = sum(
            1 for sid in memory_store.session_ids()
            if memory_store.should_summarise(sid)
            and memory_store.save_summary(sid, user_id=None)
        )
        return f"summarised_{summarised}" if summarised else "no_summaries_needed"
    except Exception as exc:
        logger.warning("agent_manager: memory observation failed: %s", exc)
        return f"error: {exc}"


_OBSERVATIONS = [
    ("django",             _observe_django),
    ("unanswered_threads", _observe_unanswered_threads),
    ("catalog_freshness",  _observe_catalog_freshness),
    ("scheduler_health",   _observe_scheduler_health),
    ("qdrant",             _observe_qdrant),
    ("gemini",             _observe_gemini),
    ("memory_summaries",   _observe_memory_summaries),
]


def _run_observation_cycle() -> Dict[str, str]:
    """
    Run all observations under a lock to prevent overlapping cycles.
    Each observation is isolated — one failure never stops the others.
    """
    if not _obs_lock.acquire(blocking=False):
        return {"skipped": "previous_cycle_still_running"}

    results: Dict[str, str] = {}
    try:
        for name, fn in _OBSERVATIONS:
            try:
                results[name] = fn()
            except Exception as exc:
                results[name] = f"error: {exc}"
                logger.error("agent_manager: observation %r crashed: %s", name, exc)
    finally:
        _obs_lock.release()

    return results


def _manager_loop() -> None:
    agent_manager_status["running"]    = True
    agent_manager_status["started_at"] = datetime.now(tz=timezone.utc).isoformat()
    logger.info("AgentManager started (%d observations, interval=%ds)",
                len(_OBSERVATIONS), _CHECK_INTERVAL)

    while not _stop_event.is_set():
        try:
            results = _run_observation_cycle()
            now = datetime.now(tz=timezone.utc).isoformat()
            agent_manager_status["last_check_at"]  = now
            agent_manager_status["last_success_at"] = now

            history: List = agent_manager_status["observations"]
            history.append({"at": now, "results": results})
            if len(history) > _MAX_OBS_HISTORY:
                agent_manager_status["observations"] = history[-_MAX_OBS_HISTORY:]

            logger.debug("agent_manager: cycle: %s", results)

        except Exception as exc:
            now = datetime.now(tz=timezone.utc).isoformat()
            agent_manager_status["last_error_at"] = now
            errs: List = agent_manager_status["errors"]
            errs.append({"at": now, "error": str(exc)})
            if len(errs) > _MAX_ERR_HISTORY:
                agent_manager_status["errors"] = errs[-_MAX_ERR_HISTORY:]
            logger.error("agent_manager: cycle error: %s", exc, exc_info=True)

        _stop_event.wait(timeout=_CHECK_INTERVAL)

    agent_manager_status["running"] = False
    logger.info("AgentManager stopped.")


def start_agent_manager(daemon: bool = True) -> threading.Thread:
    global _manager_thread
    if _manager_thread and _manager_thread.is_alive():
        logger.debug("agent_manager: already running.")
        return _manager_thread
    _stop_event.clear()
    _manager_thread = threading.Thread(
        target=_manager_loop, name="elimu-agent-manager", daemon=daemon,
    )
    _manager_thread.start()
    return _manager_thread


def stop_agent_manager() -> None:
    global _manager_thread
    _stop_event.set()
    if _manager_thread and _manager_thread.is_alive():
        _manager_thread.join(timeout=10)
    agent_manager_status["running"] = False
    logger.info("AgentManager shutdown complete.")


def get_status() -> Dict[str, Any]:
    return dict(agent_manager_status)
