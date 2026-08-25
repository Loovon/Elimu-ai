# -*- coding: utf-8 -*-
"""
elimu_ai/tools/answer.py

Background answer bot — NO Django ORM.
All forum operations go through ElimuAPIClient HTTP calls.

Idempotency: each answer carries a stable key (ai-forum-answer-{thread_id})
so retrying after a network failure never posts duplicate answers.

Phase 3: full diagnostic logging at every stage + robust post_count handling.
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
    threads = get_unanswered_threads(cutoff_hours=3)
    logger.info("answer: API returned %d threads", len(threads))
    return threads


def _get_post_count(thread: Dict) -> int:
    """
    Robustly extract post count from a thread dict.
    Handles: post_count, posts_count, num_posts, posts (list).
    """
    for field in ("post_count", "posts_count", "num_posts", "reply_count"):
        val = thread.get(field)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    # If posts is a list, count it
    posts = thread.get("posts")
    if isinstance(posts, list):
        return len(posts)
    return 0


def _build_context_aware_answer(thread: Dict) -> Optional[str]:
    """
    Build a context-aware answer for a thread.
    Returns the answer string, or None if nothing useful was found.
    """
    title = thread.get("title", "")
    body  = thread.get("body", thread.get("content", thread.get("opening_post", "")))

    search_query = title
    if body:
        search_query = f"{title}. {body[:200]}"

    from elimu_ai.tools.library import find_materials
    materials = find_materials(search_query)

    # Prefer real document links over browse fallbacks
    if materials and "elimulibrary.com/site/document/" not in materials:
        materials_title = find_materials(title)
        if "elimulibrary.com/site/document/" in materials_title:
            materials = materials_title

    return materials or None


def answer_unanswered_threads() -> int:
    """
    Iterate unanswered threads, generate context-aware AI answers, post via HTTP.
    Returns the number of threads successfully answered.

    Phase 3: diagnostic logging at every stage.
    """
    from elimu_ai.tools.forum import post_moderated_reply

    threads = unanswered_threads()
    if not threads:
        logger.info("answer: no threads returned from API — nothing to answer")
        return 0

    logger.info("answer: evaluating %d threads for unanswered status", len(threads))

    count = 0
    for thread in threads:
        thread_id  = thread.get("id")
        title      = thread.get("title", "")
        post_count = _get_post_count(thread)

        if not thread_id or not title:
            logger.debug("answer: skipping thread (missing id or title): %r", thread)
            continue

        # Only answer threads with exactly 1 post (the opening post)
        if post_count != 1:
            logger.debug(
                "answer: skipping thread=%d %r (post_count=%d, need exactly 1)",
                thread_id, title[:60], post_count,
            )
            continue

        logger.info(
            "answer: ELIGIBLE thread=%d %r post_count=%d — generating answer",
            thread_id, title[:60], post_count,
        )

        try:
            content = _build_context_aware_answer(thread)
            if not content:
                logger.info(
                    "answer: no content generated for thread=%d %r — skipping",
                    thread_id, title[:60],
                )
                continue

            logger.info(
                "answer: posting reply to thread=%d persona=librarian_01 "
                "content_len=%d",
                thread_id, len(content),
            )

            ok = post_moderated_reply(
                thread_id=thread_id,
                content=content,
                persona_name="librarian_01",
                idempotency_key=f"ai-forum-answer-{thread_id}",
                persona_key="librarian_01",
            )
            if ok:
                count += 1
                logger.info(
                    "answer: successfully answered thread=%d %r",
                    thread_id, title[:60],
                )
            else:
                logger.info(
                    "answer: reply blocked by moderation for thread=%d %r",
                    thread_id, title[:60],
                )
        except Exception as exc:
            logger.error("answer: failed on thread=%d: %s", thread_id, exc)

    logger.info("answer: completed — answered %d thread(s)", count)
    return count

