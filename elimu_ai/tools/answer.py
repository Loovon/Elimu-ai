"""
elimu_ai/tools/answer.py

Background answer bot — auto-answers unanswered forum threads.
Responsibilities:
  - unanswered_threads()         → QuerySet
  - answer_unanswered_threads()  → int  (threads answered)

Requires Django to be configured.
"""

from __future__ import annotations

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)


def unanswered_threads():
    """Return threads older than 3 hours that have received no replies."""
    from django.utils import timezone
    from forum.models import Thread
    cutoff = timezone.now() - timedelta(hours=3)
    return Thread.objects.filter(created_at__lt=cutoff)


def answer_unanswered_threads() -> int:
    """
    Post AI-generated answers to threads that have only the opening post.
    Returns the count of threads answered.
    """
    from django.contrib.auth.models import User
    from forum.models import Post
    from elimu_ai.personas import TEACHER
    from elimu_ai.tools.library import find_materials

    ai_user, _ = User.objects.get_or_create(
        username=TEACHER,
        defaults={"email": "teacherai@elimutalks.ai", "is_active": True},
    )

    count = 0
    for thread in unanswered_threads():
        if thread.posts.count() == 1:
            try:
                answer = find_materials(thread.title)
                Post.objects.create(thread=thread, author=ai_user, content=answer)
                count += 1
                logger.debug("answer: replied to thread %r", thread.title[:60])
            except Exception as exc:
                logger.error("answer: failed to reply to thread %d: %s", thread.pk, exc)

    return count
