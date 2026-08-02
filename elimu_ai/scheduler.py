"""
elimu_ai/scheduler.py

Background agent scheduler.

Responsibilities:
  - Run recurring background tasks independently of the chat API.
  - Each task is isolated and fails gracefully.

Supported tasks:
  - answer_unanswered     : Auto-answer forum threads with no replies
  - generate_discussions  : Post daily discussion starters to the forum
  - recommend_resources   : Suggest materials for popular unanswered topics
  - moderate_content      : Scan recent posts for spam / policy violations
  - catalog_sync          : Trigger re-indexing of the Elimu Library catalog (hook)

Usage:
    # Run all tasks once (e.g. from a cron job or management command):
    from elimu_ai.scheduler import run_all_tasks
    run_all_tasks()

    # Or run individual tasks:
    from elimu_ai.scheduler import task_answer_unanswered
    task_answer_unanswered()
"""

from __future__ import annotations

import logging
from typing import Callable, List

logger = logging.getLogger(__name__)


# ── Individual tasks ──────────────────────────────────────────────────────────

def task_answer_unanswered() -> None:
    """Auto-answer forum threads that have been unanswered for 3+ hours."""
    try:
        from elimu_ai.tools.answer import answer_unanswered_threads
        count = answer_unanswered_threads()
        logger.info("task_answer_unanswered: answered %d threads.", count)
    except Exception as exc:
        logger.error("task_answer_unanswered failed: %s", exc)


def task_generate_discussions() -> None:
    """Post a daily discussion starter to the forum."""
    _DAILY_TOPICS = [
        "What is the hardest topic in KCSE Mathematics and why?",
        "How can students improve their English writing skills?",
        "What study habits work best for CBC learners?",
        "Share a Biology concept you found confusing and how you mastered it.",
        "What is the most useful subject for everyday life in Kenya?",
    ]
    try:
        from datetime import date
        from elimu_ai.tools.forum import create_discussion
        # Pick a topic based on the day of year to rotate through the list
        topic = _DAILY_TOPICS[date.today().timetuple().tm_yday % len(_DAILY_TOPICS)]
        result = create_discussion(topic)
        logger.info("task_generate_discussions: %s", result[:80])
    except Exception as exc:
        logger.error("task_generate_discussions failed: %s", exc)


def task_recommend_resources() -> None:
    """Post resource recommendations to threads that ask for materials."""
    try:
        from elimu_ai.tools.answer import unanswered_threads
        from elimu_ai.tools.library import find_materials
        from elimu_ai.tools.forum import _django_available
        if not _django_available():
            return
        from django.contrib.auth.models import User
        from forum.models import Post
        from elimu_ai.personas import LIBRARIAN

        ai_user, _ = User.objects.get_or_create(
            username=LIBRARIAN,
            defaults={"email": "librarian@elimutalks.ai", "is_active": True},
        )
        count = 0
        for thread in unanswered_threads():
            lower = thread.title.lower()
            if any(kw in lower for kw in ["notes", "revision", "past paper", "scheme", "resources"]):
                if thread.posts.count() == 1:
                    answer = find_materials(thread.title)
                    Post.objects.create(thread=thread, author=ai_user, content=answer)
                    count += 1
        logger.info("task_recommend_resources: posted %d resource replies.", count)
    except Exception as exc:
        logger.error("task_recommend_resources failed: %s", exc)


def task_moderate_content() -> None:
    """Scan recent posts for spam and policy violations."""
    try:
        from elimu_ai.tools.moderation import moderate
        from elimu_ai.tools.forum import _django_available
        if not _django_available():
            return
        from django.utils import timezone
        from datetime import timedelta
        from forum.models import Post

        cutoff = timezone.now() - timedelta(hours=1)
        recent_posts = Post.objects.filter(created_at__gte=cutoff)
        flagged = 0
        for post in recent_posts:
            result = moderate(post.content or "")
            if result != "Content approved.":
                logger.warning("Flagged post #%s: %s", post.pk, result)
                flagged += 1
        logger.info("task_moderate_content: %d/%d posts flagged.", flagged, recent_posts.count())
    except Exception as exc:
        logger.error("task_moderate_content failed: %s", exc)


def task_catalog_sync() -> None:
    """
    Hook point for triggering a catalog re-index.
    Actual crawl/index logic lives in the Django management command
    or the crawl scripts at the project root.
    """
    logger.info(
        "task_catalog_sync: catalog sync hook called. "
        "Run 'python manage.py index_elimu_catalog' to rebuild the index."
    )


# ── Task runner ───────────────────────────────────────────────────────────────

_ALL_TASKS: List[Callable] = [
    task_answer_unanswered,
    task_generate_discussions,
    task_recommend_resources,
    task_moderate_content,
    task_catalog_sync,
]


def run_all_tasks() -> None:
    """Run every registered background task in sequence, logging failures."""
    logger.info("Background agent: running %d tasks.", len(_ALL_TASKS))
    for task in _ALL_TASKS:
        task()
    logger.info("Background agent: all tasks complete.")
