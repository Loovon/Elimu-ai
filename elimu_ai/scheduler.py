"""
elimu_ai/scheduler.py

Autonomous background scheduler powered by APScheduler 3.x.

Design:
  - Each task runs on its own configurable interval.
  - Tasks are isolated — one failure never affects others.
  - Graceful shutdown on SIGINT / SIGTERM.
  - Health status is exposed via the scheduler_status dict (read by service.py).
  - New tasks can be added by registering them in _TASK_REGISTRY.

Usage — embed in the FastAPI process (via app.py):
    from elimu_ai.scheduler import start_scheduler
    start_scheduler(daemon=True)

Usage — run standalone as a long-running process:
    python -m elimu_ai.scheduler

Usage — run all tasks once (management command / testing):
    from elimu_ai.scheduler import run_all_tasks
    run_all_tasks()
"""

from __future__ import annotations

import logging
import signal
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from elimu_ai.config import (
    SCHEDULER_ANSWER_INTERVAL,
    SCHEDULER_CATALOG_INTERVAL,
    SCHEDULER_DISCUSS_INTERVAL,
    SCHEDULER_MODERATE_INTERVAL,
    SCHEDULER_RECOMMEND_INTERVAL,
)

logger = logging.getLogger(__name__)

# ── Shared status dict (read by /scheduler/status endpoint) ──────────────────
# Written here; read by service.py via a lazy import to avoid circular imports.

scheduler_status: Dict[str, Any] = {
    "running":    False,
    "started_at": None,
    "last_run":   {},
    "errors":     {},
}


# ── Task implementations ──────────────────────────────────────────────────────

def task_answer_unanswered() -> str:
    """Auto-answer forum threads that have been unanswered for 3+ hours."""
    try:
        from elimu_ai.tools.answer import answer_unanswered_threads
        count = answer_unanswered_threads()
        return f"Answered {count} threads."
    except Exception as exc:
        logger.error("task_answer_unanswered failed: %s", exc)
        return f"Error: {exc}"


def task_generate_discussions() -> str:
    """Post a rotating daily discussion starter to the ElimuTalks forum."""
    _TOPICS: List[str] = [
        "What is the hardest topic in KCSE Mathematics and why?",
        "How can students improve their English writing skills?",
        "What study habits work best for CBC learners?",
        "Share a Biology concept you found confusing and how you mastered it.",
        "What is the most useful subject for everyday life in Kenya?",
        "How should schools prepare students for KCSE exams?",
        "What role should parents play in their child's academic life?",
        "Which CBC subjects do you find most interesting and why?",
    ]
    try:
        from elimu_ai.tools.forum import create_discussion
        topic = _TOPICS[datetime.now(tz=timezone.utc).timetuple().tm_yday % len(_TOPICS)]
        result = create_discussion(topic)
        return result[:120]
    except Exception as exc:
        logger.error("task_generate_discussions failed: %s", exc)
        return f"Error: {exc}"


def task_recommend_resources() -> str:
    """Post catalog resource recommendations to unanswered resource-request threads."""
    try:
        from elimu_ai.tools.forum import _django_available
        if not _django_available():
            return "Django not available — skipped."

        from django.contrib.auth.models import User
        from forum.models import Post
        from elimu_ai.personas import LIBRARIAN
        from elimu_ai.tools.answer import unanswered_threads
        from elimu_ai.tools.library import find_materials

        _RESOURCE_KEYWORDS = [
            "notes", "revision", "past paper", "scheme", "resources",
            "materials", "lesson plan", "assessment", "homework",
        ]

        ai_user, _ = User.objects.get_or_create(
            username=LIBRARIAN,
            defaults={"email": "librarian@elimutalks.ai", "is_active": True},
        )
        count = 0
        for thread in unanswered_threads():
            lower = thread.title.lower()
            if any(kw in lower for kw in _RESOURCE_KEYWORDS):
                if thread.posts.count() == 1:
                    answer = find_materials(thread.title)
                    Post.objects.create(thread=thread, author=ai_user, content=answer)
                    count += 1
        return f"Posted {count} resource replies."
    except Exception as exc:
        logger.error("task_recommend_resources failed: %s", exc)
        return f"Error: {exc}"


def task_moderate_content() -> str:
    """Scan posts from the last hour for spam and policy violations."""
    try:
        from elimu_ai.tools.forum import _django_available
        if not _django_available():
            return "Django not available — skipped."

        from datetime import timedelta
        from django.utils import timezone as dj_timezone
        from forum.models import Post
        from elimu_ai.tools.moderation import moderate

        cutoff = dj_timezone.now() - timedelta(hours=1)
        recent_posts = Post.objects.filter(created_at__gte=cutoff)
        total = recent_posts.count()
        flagged = 0
        for post in recent_posts:
            result = moderate(post.content or "")
            if result != "Content approved.":
                logger.warning("scheduler [moderate]: post #%d flagged: %s", post.pk, result)
                flagged += 1
        return f"Scanned {total} posts, flagged {flagged}."
    except Exception as exc:
        logger.error("task_moderate_content failed: %s", exc)
        return f"Error: {exc}"


def task_catalog_sync() -> str:
    """
    Refresh the in-memory catalog cache by reloading from disk.
    The actual crawl/index is triggered externally via:
        python manage.py index_elimu_catalog
    """
    try:
        import elimu_ai.catalog_search as cs
        cs._index   = None
        cs._catalog = None
        cs._load()
        return "Catalog cache refreshed."
    except Exception as exc:
        logger.error("task_catalog_sync failed: %s", exc)
        return f"Error: {exc}"


# ── Task registry ─────────────────────────────────────────────────────────────
# (name, function, interval_seconds)
# Add new tasks here — they will be automatically registered with APScheduler.

_TASK_REGISTRY: List[Tuple[str, Callable[[], str], int]] = [
    ("answer_unanswered",    task_answer_unanswered,    SCHEDULER_ANSWER_INTERVAL),
    ("generate_discussions", task_generate_discussions,  SCHEDULER_DISCUSS_INTERVAL),
    ("recommend_resources",  task_recommend_resources,   SCHEDULER_RECOMMEND_INTERVAL),
    ("moderate_content",     task_moderate_content,      SCHEDULER_MODERATE_INTERVAL),
    ("catalog_sync",         task_catalog_sync,          SCHEDULER_CATALOG_INTERVAL),
]


# ── APScheduler wrapper ───────────────────────────────────────────────────────

def _make_job(name: str, fn: Callable[[], str]) -> Callable[[], None]:
    """
    Wrap a task function so APScheduler can call it.
    Updates scheduler_status with the result of each run.
    """
    def job() -> None:
        logger.debug("scheduler: starting task %r", name)
        try:
            result = fn()
        except Exception as exc:
            result = f"Error: {exc}"
            logger.error("scheduler: task %r raised: %s", name, exc)

        now = datetime.now(tz=timezone.utc).isoformat()
        scheduler_status["last_run"][name] = {"at": now, "result": result}
        is_error = result.startswith("Error:")
        if is_error:
            scheduler_status["errors"][name] = {"at": now, "detail": result}
        else:
            scheduler_status["errors"].pop(name, None)

        log = logger.error if is_error else logger.info
        log("scheduler [%s]: %s", name, result)

    job.__name__ = f"task_{name}"
    return job


_scheduler_instance: Optional[Any] = None   # APScheduler BackgroundScheduler
_scheduler_lock = threading.Lock()


def _build_scheduler():
    """Create and configure an APScheduler BackgroundScheduler."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.executors.pool import ThreadPoolExecutor
    from apscheduler.jobstores.memory import MemoryJobStore

    sched = BackgroundScheduler(
        jobstores={"default": MemoryJobStore()},
        executors={"default": ThreadPoolExecutor(max_workers=4)},
        job_defaults={
            "coalesce":       True,   # merge missed executions into one
            "max_instances":  1,      # prevent overlapping runs of the same job
            "misfire_grace_time": 60, # allow up to 60s late before skipping
        },
        timezone="Africa/Nairobi",
    )

    for name, fn, interval in _TASK_REGISTRY:
        sched.add_job(
            func=_make_job(name, fn),
            trigger="interval",
            seconds=interval,
            id=name,
            name=f"ElimuAI:{name}",
            replace_existing=True,
        )
        logger.debug(
            "scheduler: registered %r (interval=%ds)", name, interval
        )

    return sched


# ── Public API ────────────────────────────────────────────────────────────────

def start_scheduler(daemon: bool = True) -> Any:
    """
    Start APScheduler in a background thread.
    Safe to call multiple times — returns the existing instance if already running.

    Parameters
    ----------
    daemon : bool
        If True, the scheduler thread exits when the main process exits.
        If False, the process will not exit until shutdown() is called.

    Returns
    -------
    APScheduler BackgroundScheduler instance.
    """
    global _scheduler_instance

    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.running:
            logger.debug("scheduler: already running — reusing existing instance.")
            return _scheduler_instance

        sched = _build_scheduler()
        sched.start(paused=False)
        _scheduler_instance = sched

    scheduler_status["running"]    = True
    scheduler_status["started_at"] = datetime.now(tz=timezone.utc).isoformat()
    logger.info(
        "APScheduler started with %d jobs: %s",
        len(_TASK_REGISTRY),
        [name for name, _, _ in _TASK_REGISTRY],
    )
    return sched


def shutdown_scheduler(wait: bool = True) -> None:
    """
    Gracefully shut down the APScheduler instance.

    Parameters
    ----------
    wait : bool
        If True, wait for currently running jobs to complete before shutting down.
    """
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance and _scheduler_instance.running:
            _scheduler_instance.shutdown(wait=wait)
            logger.info("APScheduler shut down (wait=%s).", wait)
        scheduler_status["running"] = False
        _scheduler_instance = None


def run_all_tasks() -> Dict[str, str]:
    """
    Run every registered task once immediately and return a dict of results.
    Useful for management commands, CI checks, and testing.
    Does NOT start the APScheduler loop.
    """
    results: Dict[str, str] = {}
    logger.info("run_all_tasks: running %d tasks.", len(_TASK_REGISTRY))
    for name, fn, _ in _TASK_REGISTRY:
        try:
            result = fn()
        except Exception as exc:
            result = f"Error: {exc}"
            logger.error("run_all_tasks [%s]: %s", name, exc)
        results[name] = result
        logger.info("run_all_tasks [%s]: %s", name, result)
    logger.info("run_all_tasks: complete.")
    return results


def get_status() -> Dict[str, Any]:
    """Return the current scheduler status dict (same object read by /scheduler/status)."""
    return dict(scheduler_status)


# ── Standalone entry point ────────────────────────────────────────────────────

def _run_standalone() -> None:
    """
    Run the scheduler as a long-running standalone process.
    Handles SIGINT / SIGTERM for graceful shutdown.

    Invoked by:  python -m elimu_ai.scheduler
    """
    from elimu_ai.logging_config import configure_logging
    configure_logging()

    logger.info("Starting Elimu AI scheduler (standalone mode).")
    sched = start_scheduler(daemon=False)

    stop_event = threading.Event()

    def _handle_signal(signum, frame):  # type: ignore[type-arg]
        logger.info("Received signal %d — shutting down scheduler.", signum)
        stop_event.set()

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("Scheduler running. Press Ctrl+C to stop.")
    try:
        stop_event.wait()  # block until signal received
    finally:
        shutdown_scheduler(wait=True)
        logger.info("Scheduler exited cleanly.")


if __name__ == "__main__":
    _run_standalone()
