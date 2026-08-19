"""
elimu_ai/tools/answer.py

Background answer bot — NO Django ORM.
All forum operations go through ElimuAPIClient HTTP calls.

Idempotency: each answer carry a stable key (ai-forum-answer-{thread_id})
so retrying after a network failure never posts duplicate answers.

Phase 2: answers are now context-aware (thread title + existing posts used)
and pass through local + Django moderation before posting.
"""

from __future__ import annotations

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def unanswered_threads() -> List[Dict]:
    """
    Fetch unanswered threads from Django via HTTP.
    Returns a list of thread dicts, or [] when Django is unavailable.
    """
    from elimu_ai.tools.forum import get_unanswered_threads
    return get_unanswered_threads(cutoff_hours=3)


def _build_context_aware_answer(thread: Dict) -> Optional[str]:
    """
    Build a context-aware answer for a thread.

    Uses:
    - Thread title (always available)
    - Thread body/first post if available in the thread dict
    - Relevant Elimu Library materials

    Returns the answer string, or None if nothing useful was found.
    """
    thread_id = thread.get("id")
    title = thread.get("title", "")
    body = thread.get("body", thread.get("content", ""))

    # Build the search query combining title and body snippet
    search_query = title
    if body:
        search_query = f"{title}. {body[:200]}"

    from elimu_ai.tools.library import find_materials
    materials = find_materials(search_query)

    # If only a browse fallback was returned (no real documents), try title only
    if materials and "elimulibrary.com/site/document/" not in materials:
        materials_title = find_materials(title)
        if "elimulibrary.com/site/document/" in materials_title:
            materials = materials_title

    return materials or None


def answer_unanswered_threads() -> int:
    """
    Iterate unanswered threads, generate context-aware AI answers, post via HTTP.
    Returns the number of threads successfully answered.

    Phase 2 changes:
    - Uses thread body/content for richer context (not just title)
    - Posts through post_moderated_reply (local + Django moderation gate)
    - Idempotency-Key prevents duplicate posts on retry
    """
    from elimu_ai.tools.forum import post_moderated_reply

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
            content = _build_context_aware_answer(thread)
            if not content:
                logger.debug("answer: no content for thread %d %r", thread_id, title[:60])
                continue

            ok = post_moderated_reply(
                thread_id=thread_id,
                content=content,
                persona_name="librarian",
                idempotency_key=f"ai-forum-answer-{thread_id}",
            )
            if ok:
                count += 1
                logger.debug("answer: replied to thread %d %r", thread_id, title[:60])
            else:
                logger.info(
                    "answer: reply blocked by moderation for thread %d %r",
                    thread_id, title[:60],
                )
        except Exception as exc:
            logger.error("answer: failed on thread %d: %s", thread_id, exc)

    return count
