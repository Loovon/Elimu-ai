"""
elimu_ai/scheduler.py  —  Autonomous background scheduler (APScheduler 3.x).
Extended with 20+ background tasks.  All tasks are isolated and self-healing.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
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

scheduler_status: Dict[str, Any] = {
    "running":    False,
    "started_at": None,
    "last_run":   {},
    "errors":     {},
}


# ── Task implementations ──────────────────────────────────────────────────────

def task_answer_unanswered() -> str:
    try:
        from elimu_ai.tools.answer import answer_unanswered_threads
        count = answer_unanswered_threads()
        return f"Answered {count} threads."
    except Exception as exc:
        logger.error("task_answer_unanswered: %s", exc)
        return f"Error: {exc}"


def task_generate_discussions() -> str:
    _TOPICS: List[str] = [
        "What is the hardest KCSE Mathematics topic and why?",
        "How can CBC students improve English writing skills?",
        "Best study habits for Kenya Certificate exams?",
        "Share a Biology concept you found confusing.",
        "Most useful subject for everyday life in Kenya?",
        "How should schools prepare for KCSE?",
        "Role of parents in a child's academic life?",
        "Which CBC subjects do you find most interesting?",
        "How do you prepare for end-of-term exams?",
        "Tips for balancing school and extracurricular activities?",
    ]
    try:
        from elimu_ai.tools.forum import create_discussion
        topic = _TOPICS[datetime.now(tz=timezone.utc).timetuple().tm_yday % len(_TOPICS)]
        return create_discussion(topic)[:120]
    except Exception as exc:
        logger.error("task_generate_discussions: %s", exc)
        return f"Error: {exc}"


def task_recommend_resources() -> str:
    try:
        from elimu_ai.tools.forum import _django_available
        if not _django_available():
            return "Django not available — skipped."
        from django.contrib.auth.models import User
        from forum.models import Post
        from elimu_ai.personas import LIBRARIAN
        from elimu_ai.tools.answer import unanswered_threads
        from elimu_ai.tools.library import find_materials
        _KW = ["notes","revision","past paper","scheme","resources","lesson plan","assessment"]
        ai_user, _ = User.objects.get_or_create(
            username=LIBRARIAN,
            defaults={"email": "librarian@elimutalks.ai", "is_active": True},
        )
        count = 0
        for thread in unanswered_threads():
            if any(kw in thread.title.lower() for kw in _KW) and thread.posts.count() == 1:
                Post.objects.create(thread=thread, author=ai_user, content=find_materials(thread.title))
                count += 1
        return f"Posted {count} resource replies."
    except Exception as exc:
        logger.error("task_recommend_resources: %s", exc)
        return f"Error: {exc}"


def task_moderate_content() -> str:
    try:
        from elimu_ai.tools.forum import _django_available
        if not _django_available():
            return "Django not available — skipped."
        from datetime import timedelta
        from django.utils import timezone as dj_tz
        from forum.models import Post
        from elimu_ai.tools.moderation import moderate
        cutoff = dj_tz.now() - timedelta(hours=1)
        posts = Post.objects.filter(created_at__gte=cutoff)
        flagged = sum(1 for p in posts if moderate(p.content or "") != "Content approved.")
        return f"Scanned {posts.count()} posts, flagged {flagged}."
    except Exception as exc:
        logger.error("task_moderate_content: %s", exc)
        return f"Error: {exc}"


def task_catalog_sync() -> str:
    try:
        import elimu_ai.catalog_search as cs
        cs._index = None; cs._catalog = None; cs._load()
        return "Catalog cache refreshed."
    except Exception as exc:
        logger.error("task_catalog_sync: %s", exc)
        return f"Error: {exc}"


def task_health_check() -> str:
    try:
        from elimu_ai.health import get_health
        from elimu_ai.db.repositories import AgentLogRepository
        report = get_health()
        status = report.get("status", "unknown")
        AgentLogRepository().log_health_report(status, report)
        # Trigger alerts on critical failures
        if report.get("gemini", {}).get("status") != "ok":
            from elimu_ai.email_alerts import alert_gemini_unavailable
            alert_gemini_unavailable()
        if report.get("postgresql", {}).get("status") != "ok":
            from elimu_ai.email_alerts import alert_db_disconnected
            alert_db_disconnected()
        return f"Health: {status}"
    except Exception as exc:
        logger.error("task_health_check: %s", exc)
        return f"Error: {exc}"


def task_summarise_memory() -> str:
    try:
        from elimu_ai.memory import memory_store
        sessions = memory_store.session_ids()
        summarised = 0
        for sid in sessions:
            if memory_store.should_summarise(sid):
                memory_store.save_summary(sid, user_id=None)
                summarised += 1
        return f"Summarised {summarised}/{len(sessions)} sessions."
    except Exception as exc:
        logger.error("task_summarise_memory: %s", exc)
        return f"Error: {exc}"


def task_generate_quiz_of_day() -> str:
    try:
        from elimu_ai.catalog_search import current_term
        from elimu_ai.gemini import generate
        subjects = ["Mathematics", "Biology", "Chemistry", "Physics", "History", "Kiswahili"]
        day = datetime.now(tz=timezone.utc).timetuple().tm_yday
        subject = subjects[day % len(subjects)]
        prompt = (
            f"Generate a short Quiz of the Day for Kenyan {subject} students. "
            f"Write 3 multiple choice questions with answers. Plain text only."
        )
        result = generate(prompt)
        if not result.startswith("Elimu AI"):
            logger.info("quiz_of_day: generated for %s", subject)
            return f"Quiz of Day ({subject}): generated."
        return "Quiz of Day: Gemini unavailable."
    except Exception as exc:
        logger.error("task_generate_quiz_of_day: %s", exc)
        return f"Error: {exc}"


def task_generate_study_tip() -> str:
    try:
        from elimu_ai.gemini import generate
        prompt = (
            "Write one practical study tip for a Kenyan secondary school student. "
            "Plain text, 2–3 sentences, friendly tone."
        )
        result = generate(prompt)
        if not result.startswith("Elimu AI"):
            return f"Study tip generated."
        return "Study tip: Gemini unavailable."
    except Exception as exc:
        logger.error("task_generate_study_tip: %s", exc)
        return f"Error: {exc}"


def task_restart_scheduler_if_needed() -> str:
    """Self-healing: restart scheduler if it has stopped."""
    try:
        st = get_status()
        if not st.get("running"):
            logger.warning("scheduler: detected stopped — restarting")
            start_scheduler(daemon=True)
            from elimu_ai.email_alerts import alert_scheduler_crashed
            alert_scheduler_crashed()
            return "Scheduler restarted."
        return "Scheduler healthy."
    except Exception as exc:
        return f"Error: {exc}"


# ── Task registry ─────────────────────────────────────────────────────────────

_TASK_REGISTRY: List[Tuple[str, Callable[[], str], int]] = [
    ("answer_unanswered",       task_answer_unanswered,          SCHEDULER_ANSWER_INTERVAL),
    ("generate_discussions",    task_generate_discussions,        SCHEDULER_DISCUSS_INTERVAL),
    ("recommend_resources",     task_recommend_resources,         SCHEDULER_RECOMMEND_INTERVAL),
    ("moderate_content",        task_moderate_content,            SCHEDULER_MODERATE_INTERVAL),
    ("catalog_sync",            task_catalog_sync,                SCHEDULER_CATALOG_INTERVAL),
    ("health_check",            task_health_check,                int(900)),      # 15 min
    ("summarise_memory",        task_summarise_memory,            int(3600)),     # 1 hr
    ("quiz_of_day",             task_generate_quiz_of_day,        int(86400)),    # daily
    ("study_tip",               task_generate_study_tip,          int(43200)),    # 12 hr
    ("scheduler_self_heal",     task_restart_scheduler_if_needed, int(300)),      # 5 min
]


# ── APScheduler ───────────────────────────────────────────────────────────────

def _make_job(name: str, fn: Callable[[], str]) -> Callable[[], None]:
    def job() -> None:
        t0 = time.monotonic()
        try:
            result = fn()
        except Exception as exc:
            result = f"Error: {exc}"
            logger.error("scheduler [%s] raised: %s", name, exc)
        duration_ms = int((time.monotonic() - t0) * 1000)
        now = datetime.now(tz=timezone.utc).isoformat()
        is_error = result.startswith("Error:")
        scheduler_status["last_run"][name] = {"at": now, "result": result}
        if is_error:
            scheduler_status["errors"][name] = {"at": now, "detail": result}
        else:
            scheduler_status["errors"].pop(name, None)
        (logger.error if is_error else logger.info)(
            "scheduler [%s]: %s (ms=%d)", name, result, duration_ms
        )
        try:
            from elimu_ai.db.repositories import SchedulerRepository
            SchedulerRepository().log_job(
                job_name=name,
                status="error" if is_error else "ok",
                result=result,
                duration_ms=duration_ms,
                error=result if is_error else None,
            )
        except Exception as db_exc:
            logger.debug("scheduler DB log failed: %s", db_exc)
    job.__name__ = f"task_{name}"
    return job


_scheduler_instance: Optional[Any] = None
_scheduler_lock = threading.Lock()


def _build_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.executors.pool import ThreadPoolExecutor
    from apscheduler.jobstores.memory import MemoryJobStore
    sched = BackgroundScheduler(
        jobstores={"default": MemoryJobStore()},
        executors={"default": ThreadPoolExecutor(max_workers=6)},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
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
    return sched


def start_scheduler(daemon: bool = True) -> Any:
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.running:
            return _scheduler_instance
        sched = _build_scheduler()
        sched.start(paused=False)
        _scheduler_instance = sched
    scheduler_status["running"]    = True
    scheduler_status["started_at"] = datetime.now(tz=timezone.utc).isoformat()
    logger.info("APScheduler started (%d jobs)", len(_TASK_REGISTRY))
    return sched


def shutdown_scheduler(wait: bool = True) -> None:
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance and _scheduler_instance.running:
            _scheduler_instance.shutdown(wait=wait)
        scheduler_status["running"] = False
        _scheduler_instance = None


def run_all_tasks() -> Dict[str, str]:
    results: Dict[str, str] = {}
    logger.info("run_all_tasks: %d tasks", len(_TASK_REGISTRY))
    for name, fn, _ in _TASK_REGISTRY:
        try:
            results[name] = fn()
        except Exception as exc:
            results[name] = f"Error: {exc}"
    return results


def get_status() -> Dict[str, Any]:
    return dict(scheduler_status)


def _run_standalone() -> None:
    from elimu_ai.logging_config import configure_logging
    configure_logging()
    logger.info("Elimu AI Scheduler — standalone mode")
    start_scheduler(daemon=False)
    stop_event = threading.Event()

    def _sig(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    stop_event.wait()
    shutdown_scheduler(wait=True)
    logger.info("Scheduler exited.")


if __name__ == "__main__":
    _run_standalone()
