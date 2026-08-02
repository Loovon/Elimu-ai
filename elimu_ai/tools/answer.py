"""
elimu_ai/tools/answer.py

Background answer bot — auto-answers unanswered forum threads.
Responsibilities:
  - unanswered_threads()         → QuerySet of Thread objects
  - answer_unanswered_threads()  → int (count of threads answered)

Requires Django to be configured.
Uses library.find_materials() to generate answers.
"""

from __future__ import annotations

from datetime import timedelta


def unanswered_threads():
    """Return threads older than 3 hours that have only the opening post."""
    from django.utils import timezone
    from forum.models import Thread
    cutoff = timezone.now() - timedelta(hours=3)
    return Thread.objects.filter(created_at__lt=cutoff)


def answer_unanswered_threads() -> int:
    """
    Iterate unanswered threads and post an AI-generated answer.
    Returns the number of threads answered.
    """
    from django.contrib.auth.models import User
    from forum.models import Post
    from elimu_ai.tools.library import find_materials
    from elimu_ai.personas import TEACHER

    ai_user, _ = User.objects.get_or_create(
        username=TEACHER,
        defaults={"email": "teacherai@elimutalks.ai", "is_active": True},
    )

    count = 0
    for thread in unanswered_threads():
        if thread.posts.count() == 1:
            answer = find_materials(thread.title)
            Post.objects.create(thread=thread, author=ai_user, content=answer)
            count += 1
    return count
