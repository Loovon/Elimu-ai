"""
elimu_ai/agent_manager.py

Background Agent Manager — the autonomous observer and coordinator.

Runs continuously alongside the FastAPI process (as a daemon thread).
Observes the database and scheduler, launches jobs, manages retries,
and maintains platform health.

Responsibilities:
  - Watch for unanswered forum discussions
  - Watch for new catalog documents
  - Monitor scheduler job health
  - Launch background jobs on demand
  - Manage retry logic for failed jobs
  - Periodic health self-check
  - Emit structured logs for every action

Rules:
  - Never crashes on any individual error.
  - Never blocks the main thread.
  - Communicates status via agent_manager_status dict.
  - Graceful shutdown on stop_event.

Usage:
    from elimu_ai.agent_manager import start_agent_manager, stop_agent_manager
    start_agent_manager()        # call once at startup
    stop_agent_manager()         # call at shutdown
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Shared status (read by /health endpoint) ──────────────────────────────────

agent_manager_status: Dict[str, Any] = {
    "running":        False,
    "started_at":     None,
    "last_check_at":  None,
    "observations":   [],       # last N observation results
    "errors":         [],       # last N errors
    "jobs_launched":  0,
}

# Configuration
_CHECK_INTERVAL   = 60    # seconds between observation cycles
_MAX_OBS_HISTORY  = 20    # entries kept in observations list
_MAX_ERR_HISTORY  = 10    # entries kept in error list

_stop_event = threading.Event()
_manager_thread: Optional[threading.Thread] = None


# ── Observation functions ─────────────────────────────────────────────────────

def _observe_unanswered_threads() -> str:
    """Check how many forum threads are waiting for AI answers."""
    try:
        from elimu_ai.tools.forum import _django_available
        if not _django_available():
            return "django_unavailable"
        from elimu_ai.tools.answer import unanswered_threads
        count = unanswered_threads().count()
        logger.debug("agent_manager: %d unanswered threads detected", count)
        if count > 0:
            # Trigger the answer task immediately
            from elimu_ai.scheduler import task_answer_unanswered
            task_answer_unanswered()
            agent_manager_status["jobs_launched"] += 1
            return f"answered_{count}_threads"
        return "no_unanswered_threads"
    except Exception as exc:
        logger.warning("agent_manager: unanswered thread check failed: %s", exc)
        return f"error: {exc}"


def _observe_catalog_freshness() -> str:
    """Check if the catalog index is stale or missing."""
    try:
        from elimu_ai.catalog_search import catalog_available, _INDEX_PATH
        if not catalog_available():
            logger.warning("agent_manager: catalog index missing")
            return "catalog_missing"
        import pathlib
        path = pathlib.Path(str(_INDEX_PATH))
        if path.exists():
            import os
            age_hours = (time.time() - os.path.getmtime(str(path))) / 3600
            if age_hours > 24:
                logger.info("agent_manager: catalog is %.1f hours old — triggering sync", age_hours)
                from elimu_ai.scheduler import task_catalog_sync
                task_catalog_sync()
                agent_manager_status["jobs_launched"] += 1
                return f"catalog_synced_age_{age_hours:.0f}h"
        return "catalog_fresh"
    except Exception as exc:
        logger.warning("agent_manager: catalog check failed: %s", exc)
        return f"error: {exc}"


def _observe_scheduler_health() -> str:
    """Check that the APScheduler is running."""
    try:
        from elimu_ai.scheduler import get_status
        st = get_status()
        if not st.get("running"):
            logger.warning("agent_manager: scheduler is not running — attempting restart")
            from elimu_ai.scheduler import start_scheduler
            start_scheduler(daemon=True)
            agent_manager_status["jobs_launched"] += 1
            return "scheduler_restarted"
        errors = st.get("errors", {})
        if errors:
            return f"scheduler_running_with_{len(errors)}_errors"
        return "scheduler_healthy"
    except Exception as exc:
        logger.warning("agent_manager: scheduler health check failed: %s", exc)
        return f"error: {exc}"


def _observe_memory_summaries() -> str:
    """Trigger memory summarisation for sessions that are due."""
    try:
        from elimu_ai.memory import memory_store
        session_ids = memory_store.session_ids()
        summarised = 0
        for sid in session_ids:
            if memory_store.should_summarise(sid):
                memory_store.save_summary(sid, user_id=None)
                summarised += 1
        if summarised:
            logger.info("agent_manager: summarised %d sessions", summarised)
            return f"summarised_{summarised}_sessions"
        return "no_summaries_needed"
    except Exception as exc:
        logger.warning("agent_manager: memory observation failed: %s", exc)
        return f"error: {exc}"


def _observe_db_health() -> str:
    """Quick DB connectivity check."""
    try:
        from elimu_ai.db.connection import db_available
        return "db_ok" if db_available() else "db_unavailable"
    except Exception as exc:
        return f"error: {exc}"


# ── Observation cycle ─────────────────────────────────────────────────────────

_OBSERVATIONS = [
    ("unanswered_threads",  _observe_unanswered_threads),
    ("catalog_freshness",   _observe_catalog_freshness),
    ("scheduler_health",    _observe_scheduler_health),
    ("memory_summaries",    _observe_memory_summaries),
    ("db_health",           _observe_db_health),
]


def _run_observation_cycle() -> Dict[str, str]:
    """Run all observations and return a result dict."""
    results: Dict[str, str] = {}
    for name, fn in _OBSERVATIONS:
        try:
            results[name] = fn()
        except Exception as exc:
            results[name] = f"error: {exc}"
            logger.error("agent_manager: observation %r crashed: %s", name, exc)
    return results


# ── Main loop ─────────────────────────────────────────────────────────────────

def _manager_loop() -> None:
    """
    Main observation loop. Runs until _stop_event is set.
    """
    agent_manager_status["running"]    = True
    agent_manager_status["started_at"] = datetime.now(tz=timezone.utc).isoformat()

    logger.info(
        "AgentManager started — observing %d signals every %ds.",
        len(_OBSERVATIONS), _CHECK_INTERVAL,
    )

    while not _stop_event.is_set():
        try:
            results = _run_observation_cycle()
            now = datetime.now(tz=timezone.utc).isoformat()
            agent_manager_status["last_check_at"] = now

            obs_entry = {"at": now, "results": results}
            history: List = agent_manager_status["observations"]
            history.append(obs_entry)
            if len(history) > _MAX_OBS_HISTORY:
                agent_manager_status["observations"] = history[-_MAX_OBS_HISTORY:]

            logger.debug("agent_manager: cycle complete: %s", results)

        except Exception as exc:
            err_entry = {
                "at":    datetime.now(tz=timezone.utc).isoformat(),
                "error": str(exc),
            }
            errors: List = agent_manager_status["errors"]
            errors.append(err_entry)
            if len(errors) > _MAX_ERR_HISTORY:
                agent_manager_status["errors"] = errors[-_MAX_ERR_HISTORY:]
            logger.error("agent_manager: cycle error: %s", exc, exc_info=True)

        _stop_event.wait(timeout=_CHECK_INTERVAL)

    agent_manager_status["running"] = False
    logger.info("AgentManager stopped.")


# ── Public API ────────────────────────────────────────────────────────────────

def start_agent_manager(daemon: bool = True) -> threading.Thread:
    """
    Start the AgentManager in a background daemon thread.
    Safe to call multiple times — returns existing thread if already running.
    """
    global _manager_thread

    if _manager_thread and _manager_thread.is_alive():
        logger.debug("agent_manager: already running.")
        return _manager_thread

    _stop_event.clear()
    _manager_thread = threading.Thread(
        target=_manager_loop,
        name="elimu-agent-manager",
        daemon=daemon,
    )
    _manager_thread.start()
    return _manager_thread


def stop_agent_manager() -> None:
    """Signal the AgentManager to stop and wait for it to exit."""
    global _manager_thread
    _stop_event.set()
    if _manager_thread and _manager_thread.is_alive():
        _manager_thread.join(timeout=5)
    agent_manager_status["running"] = False
    logger.info("AgentManager shutdown complete.")


def get_status() -> Dict[str, Any]:
    """Return the current AgentManager status dict."""
    return dict(agent_manager_status)
