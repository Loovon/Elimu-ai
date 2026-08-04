"""
elimu_ai/scheduler.py

Autonomous background scheduler — runs continuously alongside the FastAPI server.

Design:
  - Each task has its own interval (configurable via environment variables in config.py).
  - Tasks run in a single background thread; each task catches its own exceptions.
  - The scheduler loop never exits unless the process is killed.
  - Status is written to service.scheduler_status so /scheduler/status can read it.

Usage (start in background thread alongside FastAPI):
    from elimu_ai.scheduler import start_scheduler
    start_scheduler()

Usage (run all tasks once, e.g. from a management command):
    from elimu_ai.scheduler import run_all_tasks
    run_all_tasks()
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List

from elimu_ai.config import (
    SCHEDULER_ANSWER_INTERVAL,
    SCHEDULER_CATALOG_INTERVAL,
    SCHEDULER_DISCUSS_INTERVAL,
    SCHEDULER_MODERATE_INTERVAL,
    SCHEDULER_RECOMMEND_INTERVAL,
)

logger = logging.getLogger(__name__)

# ── Task definitions ──────────────────────────────────────────────────────────

def task_answer_unanswered() -> str:
    """Auto-answer forum threads that have been unanswered for 3+ hours."""
    try:
        from elimu_ai.tools.answer import answer_unanswered_threads
        count = answer_unanswered_threads()
        msg = f"Answered {count} threads."
        logger.info("scheduler [answer_unanswered]: %s", msg)
        return msg
    except Exception as exc:
        logger.error("scheduler [answer_unanswered] failed: %s", exc)
        return f"Error: {exc}"


def task_generate_discussions() -> str:
    """Post a rotating daily discussion starter to the ElimuTalks forum."""
    _TOPICS = [
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
        msg = result[:120]
        logger.info("scheduler [generate_discussions]: %s", msg)
        return msg
    except Exception as exc:
        logger.error("scheduler [generate_discussions] failed: %s", exc)
        return f"Error: {exc}"


def task_recommend_resources() -> str:
    """Post resource recommendations to resource-request threads that have no replies."""
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
        msg = f"Posted {count} resource replies."
        logger.info("scheduler [recommend_resources]: %s", msg)
        return msg
    except Exception as exc:
        logger.error("scheduler [recommend_resources] failed: %s", exc)
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

        msg = f"Scanned {total} posts, flagged {flagged}."
        logger.info("scheduler [moderate_content]: %s", msg)
        return msg
    except Exception as exc:
        logger.error("scheduler [moderate_content] failed: %s", exc)
        return f"Error: {exc}"


def task_catalog_sync() -> str:
    """
    Hook for catalog re-indexing.
    Actual crawl logic lives in: python manage.py index_elimu_catalog
    This task refreshes the in-memory cache by reloading from disk.
    """
    try:
        import importlib
        import elimu_ai.catalog_search as cs
        # Reset cache so next search reloads from disk
        cs._index   = None
        cs._catalog = None
        cs._load()
        msg = "Catalog cache refreshed."
        logger.info("scheduler [catalog_sync]: %s", msg)
        return msg
    except Exception as exc:
        logger.error("scheduler [catalog_sync] failed: %s", exc)
        return f"Error: {exc}"


# ── Task registry ─────────────────────────────────────────────────────────────

# (name, function, interval_seconds)
_TASK_REGISTRY: List[tuple] = [
    ("answer_unanswered",   task_answer_unanswered,   SCHEDULER_ANSWER_INTERVAL),
    ("generate_discussions",task_generate_discussions, SCHEDULER_DISCUSS_INTERVAL),
    ("recommend_resources", task_recommend_resources,  SCHEDULER_RECOMMEND_INTERVAL),
    ("moderate_content",    task_moderate_content,     SCHEDULER_MODERATE_INTERVAL),
    ("catalog_sync",        task_catalog_sync,         SCHEDULER_CATALOG_INTERVAL),
]


# ── Continuous scheduler loop ─────────────────────────────────────────────────

class _TaskState:
    """Tracks when each task last ran."""
    def __init__(self, interval: int):
        self.interval   = interval
        self.last_ran   = 0.0       # epoch seconds
        self.last_result: str = "not yet run"

    def is_due(self) -> bool:
        return (time.monotonic() - self.last_ran) >= self.interval

    def mark_ran(self, result: str) -> None:
        self.last_ran    = time.monotonic()
        self.last_result = result


def _scheduler_loop() -> None:
    """
    Main scheduler loop. Runs each task on its own interval.
    Never exits — must be run in a daemon thread.
    """
    # Import here to avoid circular import at module level
    try:
        from elimu_ai.service import scheduler_status
        scheduler_status["running"]    = True
        scheduler_status["started_at"] = datetime.now(tz=timezone.utc).isoformat()
    except Exception:
        scheduler_status = {}

    states: Dict[str, _TaskState] = {
        name: _TaskState(interval)
        for name, _, interval in _TASK_REGISTRY
    }

    logger.info(
        "Scheduler started with %d tasks: %s",
        len(_TASK_REGISTRY),
        [name for name, _, _ in _TASK_REGISTRY],
    )

    while True:
        for name, fn, _ in _TASK_REGISTRY:
            state = states[name]
            if state.is_due():
                logger.debug("scheduler: running task %s", name)
                result = fn()
                state.mark_ran(result)
                try:
                    from elimu_ai.service import scheduler_status
                    scheduler_status["last_run"][name] = {
                        "at":     datetime.now(tz=timezone.utc).isoformat(),
                        "result": result,
                    }
                except Exception:
                    pass

        time.sleep(10)  # check task readiness every 10 seconds


# ── Public API ────────────────────────────────────────────────────────────────

def start_scheduler(daemon: bool = True) -> threading.Thread:
    """
    Start the scheduler in a background thread.
    Call this once at application startup.
    Returns the Thread object.
    """
    thread = threading.Thread(
        target=_scheduler_loop,
        name="elimu-scheduler",
        daemon=daemon,
    )
    thread.start()
    logger.info("Scheduler thread started (daemon=%s).", daemon)
    return thread


def run_all_tasks() -> Dict[str, str]:
    """
    Run every task once immediately and return a dict of results.
    Useful for management commands and testing.
    """
    results: Dict[str, str] = {}
    logger.info("run_all_tasks: running %d tasks.", len(_TASK_REGISTRY))
    for name, fn, _ in _TASK_REGISTRY:
        results[name] = fn()
    logger.info("run_all_tasks: complete.")
    return results
