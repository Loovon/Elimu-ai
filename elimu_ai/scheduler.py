"""
elimu_ai/scheduler.py — Autonomous background scheduler (APScheduler 3.x).

ZERO Django ORM imports. All forum/catalog ops go through HTTP.
Must run independently — Django being down must not crash any task.
Each task catches its own exceptions and returns a status string.
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
    SCHEDULER_RETRY_FAILURES_INTERVAL,
    MAX_RETRY_ATTEMPTS,
)

logger = logging.getLogger(__name__)

scheduler_status: Dict[str, Any] = {
    "running":    False,
    "started_at": None,
    "last_run":   {},
    "errors":     {},
}

# ── Guard: prevent multiple scheduler instances in same process ──────────────
_scheduler_instance: Optional[Any] = None
_scheduler_lock = threading.Lock()


# ── Tasks — all HTTP-based, zero Django imports ───────────────────────────────

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
    """Post catalog recommendations to resource-request threads — via HTTP."""
    try:
        from elimu_ai.tools.forum import get_unanswered_threads, post_ai_answer
        from elimu_ai.tools.library import find_materials

        _KEYWORDS = ["notes", "revision", "past paper", "scheme", "resources",
                     "lesson plan", "assessment", "homework"]
        threads = get_unanswered_threads()
        if not threads:
            return "No unanswered threads — Django may be unavailable."

        count = 0
        for thread in threads:
            thread_id  = thread.get("id")
            title      = thread.get("title", "")
            post_count = thread.get("post_count", thread.get("posts_count", 0))
            if not thread_id or not title or post_count != 1:
                continue
            if any(kw in title.lower() for kw in _KEYWORDS):
                content = find_materials(title)
                if content and post_ai_answer(
                    thread_id=thread_id,
                    content=content,
                    idempotency_key=f"ai-recommend-{thread_id}",
                ):
                    count += 1
        return f"Posted {count} resource replies."
    except Exception as exc:
        logger.error("task_recommend_resources: %s", exc)
        return f"Error: {exc}"


def task_moderate_content() -> str:
    """Scan recent posts for spam — via HTTP moderation endpoint."""
    try:
        from elimu_ai.http_client import get_client
        from elimu_ai.tools.moderation import moderate

        client = get_client()
        # GET recent posts via the Django API
        try:
            data  = client.get("/api/ai/forum/recent-posts/", {"hours": "1"})
            posts = data.get("results") or data.get("posts") or []
        except Exception:
            return "Django unavailable — moderation skipped."

        flagged = 0
        for post in posts:
            content = post.get("content", "")
            result  = moderate(content)
            if result != "Content approved.":
                logger.warning("moderate: post #%s flagged: %s", post.get("id"), result)
                flagged += 1
        return f"Scanned {len(posts)} posts, flagged {flagged}."
    except Exception as exc:
        logger.error("task_moderate_content: %s", exc)
        return f"Error: {exc}"


def task_catalog_sync() -> str:
    """Reload the local catalog cache from disk."""
    try:
        import elimu_ai.catalog_search as cs
        cs._index = None
        cs._catalog = None
        cs._load()
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
        summarised = sum(
            1 for sid in sessions
            if memory_store.should_summarise(sid)
            and memory_store.save_summary(sid, user_id=None)
        )
        return f"Summarised {summarised}/{len(sessions)} sessions."
    except Exception as exc:
        logger.error("task_summarise_memory: %s", exc)
        return f"Error: {exc}"


def task_generate_quiz_of_day() -> str:
    try:
        from elimu_ai.gemini import generate
        subjects = ["Mathematics", "Biology", "Chemistry", "Physics", "History", "Kiswahili"]
        subject  = subjects[datetime.now(tz=timezone.utc).timetuple().tm_yday % len(subjects)]
        prompt   = (
            f"Generate a short Quiz of the Day for Kenyan {subject} students. "
            "3 multiple choice questions with answers. Plain text only."
        )
        result = generate(prompt)
        if not result.startswith("Elimu AI"):
            return f"Quiz of Day ({subject}): generated."
        return "Quiz of Day: Gemini unavailable."
    except Exception as exc:
        logger.error("task_generate_quiz_of_day: %s", exc)
        return f"Error: {exc}"


def task_generate_study_tip() -> str:
    try:
        from elimu_ai.gemini import generate
        result = generate(
            "Write one practical study tip for a Kenyan secondary school student. "
            "Plain text, 2–3 sentences, friendly tone."
        )
        return "Study tip generated." if not result.startswith("Elimu AI") else "Gemini unavailable."
    except Exception as exc:
        logger.error("task_generate_study_tip: %s", exc)
        return f"Error: {exc}"


def task_scheduler_self_heal() -> str:
    """Verify scheduler is still running — no-op if healthy."""
    st = get_status()
    if not st.get("running"):
        logger.warning("scheduler: self-heal detected stopped state — restarting")
        start_scheduler(daemon=True)
        return "Scheduler restarted."
    return "Scheduler healthy."


def task_retry_failed_queries() -> str:
    """
    Retry previously unanswered/failed library queries.

    Strategy per attempt number:
      retry_count == 0 : normal retrieval (same as original request)
      retry_count == 1 : relaxed — drop metadata filters, semantic-only
      retry_count >= 2 : broadest — keyword only via catalog flat-file

    A question is marked resolved=TRUE only when actual evidence is found
    AND the answer passes VerifierAgent.  Category/browse fallbacks do NOT
    count as a resolution.

    Never generates a hallucinated answer.  Never marks resolved on empty.
    Non-fatal — any single failure is skipped and logged.
    """
    try:
        from elimu_ai.db.repositories import AgentLogRepository
        from elimu_ai.agents.verifier import VerifierAgent
        from elimu_ai.tools.library import _qdrant_search_for_query, _catalog_search_for_query
        from elimu_ai.catalog_search import _extract_from_keyword, search_catalog, format_recommendations

        repo     = AgentLogRepository()
        verifier = VerifierAgent()
        failures = repo.get_unresolved_failures_safe(
            max_retries=MAX_RETRY_ATTEMPTS, limit=20
        )
        if not failures:
            return "retry_failed_queries: nothing to retry."

        resolved_count  = 0
        attempted_count = 0

        for row in failures:
            fid      = row["id"]
            question = row["question"]
            retries  = row["retry_count"]

            try:
                attempted_count += 1

                # Extract structure from the question text
                grade, subject, term, year = _extract_from_keyword(question)

                if retries == 0:
                    # Attempt 1: normal retrieval with metadata filters
                    hits = _qdrant_search_for_query(grade, subject, term, year,
                                                    None, None, question)
                elif retries == 1:
                    # Attempt 2: relaxed — no metadata filters, semantic only
                    from elimu_ai.qdrant_db import search as qdrant_search
                    raw_hits = qdrant_search(question, score_threshold=0.0)
                    hits = []
                    for h in raw_hits:
                        p = h.payload or {}
                        url = p.get("url") or p.get("referral_url") or ""
                        if url:
                            hits.append({
                                "source":   "qdrant",
                                "score":    h.score,
                                "title":    p.get("title", ""),
                                "url":      url,
                                "grade":    p.get("grade", ""),
                                "subject":  p.get("subject", ""),
                                "term":     p.get("term", ""),
                                "year":     p.get("year", ""),
                                "doctype":  p.get("doctype", ""),
                                "audience": p.get("audience", ""),
                                "price":    p.get("price"),
                                "description": p.get("description", ""),
                                "curriculum":  p.get("curriculum", ""),
                            })
                else:
                    # Attempt 3: catalog flat-file keyword search only
                    docs = search_catalog(keyword=question, max_results=5)
                    hits = [
                        {
                            "source": "catalog", "score": 0.0,
                            "title": d.get("title", ""), "url": d.get("url", ""),
                            "grade": d.get("grade", ""), "subject": d.get("subject", ""),
                            "term":  d.get("term", ""),  "year":    d.get("year", ""),
                            "doctype": d.get("doctype", ""), "audience": d.get("audience", ""),
                            "price": d.get("price"), "description": d.get("description", ""),
                            "curriculum": d.get("curriculum", ""),
                        }
                        for d in docs if d.get("url")
                    ]

                if not hits:
                    # No evidence found — increment retry count, leave unresolved
                    repo.increment_retry(fid)
                    logger.info("retry_failed_queries: no hits for %r (attempt %d)",
                                question[:60], retries + 1)
                    continue

                # Format the evidence and verify
                from elimu_ai.tools.library import _format_evidence
                answer = _format_evidence(hits[:5], question)
                result = verifier.verify(answer, question, [])

                if result.passed:
                    repo.mark_resolved(fid)
                    resolved_count += 1
                    logger.info(
                        "retry_failed_queries: resolved %r after %d attempt(s)",
                        question[:60], retries + 1,
                    )
                    # Cache the result so live requests can find it immediately
                    _cache_resolved_answer(question, answer)
                else:
                    repo.increment_retry(fid)
                    logger.info(
                        "retry_failed_queries: evidence found but verification failed "
                        "for %r — issues=%s",
                        question[:60], result.issues,
                    )

            except Exception as row_exc:
                logger.warning("retry_failed_queries: error on row %d: %s", fid, row_exc)
                try:
                    repo.increment_retry(fid)
                except Exception:
                    pass

        return (
            f"retry_failed_queries: attempted={attempted_count} "
            f"resolved={resolved_count} remaining={attempted_count - resolved_count}"
        )

    except Exception as exc:
        logger.error("task_retry_failed_queries: %s", exc)
        return f"Error: {exc}"


def _cache_resolved_answer(question: str, answer: str) -> None:
    """Store a verified retry result in ai_recommendation_cache. Non-fatal."""
    try:
        import hashlib
        from elimu_ai.db.repositories import RecommendationRepository
        cache_key = "retry:" + hashlib.sha256(question.lower().strip().encode()).hexdigest()[:32]
        RecommendationRepository().set_cached(
            cache_key=cache_key,
            result_json=answer,
            ttl_hours=48,
        )
    except Exception as exc:
        logger.debug("_cache_resolved_answer: %s", exc)


# ── Task registry ─────────────────────────────────────────────────────────────

_TASK_REGISTRY: List[Tuple[str, Callable[[], str], int]] = [
    ("answer_unanswered",    task_answer_unanswered,    SCHEDULER_ANSWER_INTERVAL),
    ("generate_discussions", task_generate_discussions,  SCHEDULER_DISCUSS_INTERVAL),
    ("recommend_resources",  task_recommend_resources,   SCHEDULER_RECOMMEND_INTERVAL),
    ("moderate_content",     task_moderate_content,      SCHEDULER_MODERATE_INTERVAL),
    ("catalog_sync",         task_catalog_sync,          SCHEDULER_CATALOG_INTERVAL),
    ("health_check",         task_health_check,          900),
    ("summarise_memory",     task_summarise_memory,      3600),
    ("quiz_of_day",          task_generate_quiz_of_day,  86400),
    ("study_tip",            task_generate_study_tip,    43200),
    ("scheduler_self_heal",  task_scheduler_self_heal,   300),
    ("retry_failed_queries", task_retry_failed_queries,  SCHEDULER_RETRY_FAILURES_INTERVAL),
]


def _make_job(name: str, fn: Callable[[], str]) -> Callable[[], None]:
    def job() -> None:
        t0 = time.monotonic()
        try:
            result = fn()
        except Exception as exc:
            result = f"Error: {exc}"
            logger.error("scheduler [%s] raised: %s", name, exc)
        duration_ms = int((time.monotonic() - t0) * 1000)
        now      = datetime.now(tz=timezone.utc).isoformat()
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
            logger.debug("scheduler: DB log failed (non-fatal): %s", db_exc)
    job.__name__ = f"task_{name}"
    return job


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
    """Start APScheduler. Safe to call multiple times — reuses running instance."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.running:
            logger.debug("scheduler: already running — reusing.")
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
    logger.info("APScheduler shut down (wait=%s).", wait)


def run_all_tasks() -> Dict[str, str]:
    results: Dict[str, str] = {}
    for name, fn, _ in _TASK_REGISTRY:
        try:
            results[name] = fn()
        except Exception as exc:
            results[name] = f"Error: {exc}"
    return results


def get_status() -> Dict[str, Any]:
    return dict(scheduler_status)


def _run_standalone() -> None:
    """Entry point for: python -m elimu_ai.scheduler"""
    from elimu_ai.logging_config import configure_logging
    configure_logging()
    logger.info("Elimu AI Scheduler — standalone mode")
    start_scheduler(daemon=False)
    stop_event = threading.Event()

    def _sig(signum, frame):
        logger.info("Signal %d received — shutting down.", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    stop_event.wait()
    shutdown_scheduler(wait=True)
    logger.info("Scheduler exited.")


if __name__ == "__main__":
    _run_standalone()
