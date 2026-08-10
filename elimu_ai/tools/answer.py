"""
elimu_ai/tools/answer.py

Background answer bot — NO Django ORM.
All forum operations go through ElimuAPIClient HTTP calls.

Idempotency: each answer carry a stable key (ai-forum-answer-{thread_id})
so retrying after a network failure never posts duplicate answers.
"""

from __future__ import annotations

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


def unanswered_threads() -> List[Dict]:
    """
    Fetch unanswered threads from Django via HTTP.
    Returns a list of thread dicts, or [] when Django is unavailable.
    """
    from elimu_ai.tools.forum import get_unanswered_threads
    return get_unanswered_threads(cutoff_hours=3)


def answer_unanswered_threads() -> int:
    """
    Iterate unanswered threads, generate AI answers, post via HTTP.
    Returns the number of threads successfully answered.
    Idempotency-Key prevents duplicate posts on retry.
    """
    from elimu_ai.tools.library import find_materials
    from elimu_ai.tools.forum import post_ai_answer

    threads = unanswered_threads()
    if not threads:
        logger.debug("answer: no unanswered threads.")
        return 0

    count = 0
    for thread in threads:
        thread_id = thread.get("id")
        title     = thread.get("title", "")
        if not thread_id or not title:
            continue

        # Only answer threads with exactly 1 post (the opening post)
        post_count = thread.get("post_count", thread.get("posts_count", 0))
        if post_count != 1:
            continue

        try:
            content = find_materials(title)
            if not content:
                continue
            ok = post_ai_answer(
                thread_id=thread_id,
                content=content,
                idempotency_key=f"ai-forum-answer-{thread_id}",
            )
            if ok:
                count += 1
                logger.debug("answer: replied to thread %d %r", thread_id, title[:60])
        except Exception as exc:
            logger.error("answer: failed on thread %d: %s", thread_id, exc)

    return count
