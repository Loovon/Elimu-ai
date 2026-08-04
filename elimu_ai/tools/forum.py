"""
elimu_ai/tools/forum.py

Forum tool — Django-aware forum thread management.
Responsibilities:
  - generate_forum_post(topic)          → dict {title, body}
  - save_forum_post(title, body, ...)   → Thread | None
  - find_existing_threads(topic)        → str | None
  - create_discussion(topic)            → str

Rules:
  - All Django ORM access is isolated in this module.
  - Gracefully degrades when Django is not configured.
  - Never imports service.py.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from elimu_ai.gemini import generate
from elimu_ai.personas import COMMUNITY
from elimu_ai.prompts import FORUM_POST_PROMPT

logger = logging.getLogger(__name__)


# ── Django availability ───────────────────────────────────────────────────────

def _django_available() -> bool:
    """Return True if Django is installed and its settings are configured."""
    try:
        from django.conf import settings
        return settings.configured
    except Exception:
        return False


def _unique_slug(title: str) -> str:
    """Generate a slug that is unique within the Thread table."""
    try:
        from django.utils.text import slugify
        from forum.models import Thread
        slug = slugify(title)
        base, counter = slug, 1
        while Thread.objects.filter(slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug
    except Exception:
        return re.sub(r"[^\w-]", "-", title.lower())[:60]


def _pick_category(topic: str) -> str:
    """Map topic keywords to a forum category slug."""
    lower = topic.lower()
    if any(k in lower for k in ("kcse", "form 4", "form four")):
        return "kcse"
    if "cbc" in lower:
        return "cbc"
    if any(k in lower for k in ("teacher", "classroom", "scheme", "lesson plan")):
        return "teachers"
    if any(k in lower for k in ("parent", "family", "homework")):
        return "parents"
    return "revision"


# ── Core functions ────────────────────────────────────────────────────────────

def generate_forum_post(topic: str) -> dict:
    """
    Ask Gemini to generate a forum post for the topic.
    Returns {title: str, body: str}. Falls back to plain text on parse failure.
    """
    prompt = FORUM_POST_PROMPT.format(topic=topic)
    raw = generate(prompt)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    logger.warning("forum: could not parse JSON from Gemini response.")
    return {"title": f"Discussion: {topic}", "body": raw.strip()}


def save_forum_post(
    title: str,
    body: str,
    category_slug: str,
    persona: str = COMMUNITY,
) -> Optional[object]:
    """
    Create a Thread and opening Post in the Django database.
    Returns the Thread instance, or None if Django is unavailable or fails.
    """
    if not _django_available():
        return None
    try:
        from django.contrib.auth.models import User
        from forum.models import Category, Post, Thread

        category = Category.objects.filter(slug=category_slug).first()
        if not category:
            category = Category.objects.first()
        if not category:
            logger.warning("forum: no category found for slug=%r", category_slug)
            return None

        user, _ = User.objects.get_or_create(
            username=persona,
            defaults={"email": f"{persona.lower()}@elimutalks.ai", "is_active": True},
        )
        thread = Thread.objects.create(
            title=title,
            slug=_unique_slug(title),
            category=category,
            author=user,
        )
        Post.objects.create(thread=thread, author=user, content=body)
        logger.info("forum: created thread %r (slug=%s)", thread.title, thread.slug)
        return thread
    except Exception as exc:
        logger.error("forum: save_forum_post failed: %s", exc)
        return None


def find_existing_threads(topic: str) -> Optional[str]:
    """
    Search existing Django threads related to the topic.
    Returns formatted text if matches found, None otherwise.
    """
    if not _django_available():
        return None
    try:
        from django.db.models import Q
        from forum.models import Thread

        keywords = [w for w in topic.lower().split() if len(w) > 3]
        if not keywords:
            return None

        q = Q()
        for kw in keywords[:4]:
            q |= Q(title__icontains=kw)

        existing = Thread.objects.filter(q).select_related("category")[:3]
        if not existing.exists():
            return None

        lines = [
            "There are already some great discussions about this on ElimuTalks:",
            "",
        ]
        for t in existing:
            lines.append(f"- {t.title}")
            lines.append(f"  Category: {t.category.name}")
            lines.append(f"  /thread/{t.slug}/")
            lines.append("")
        lines.append("You can start a new thread if you have a different angle on this topic.")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("forum: find_existing_threads failed: %s", exc)
        return None


def create_discussion(topic: str) -> str:
    """
    Orchestrates community discussion creation:
    1. Check for existing threads — return them if found.
    2. Generate a new post via Gemini.
    3. Save to Django forum if available.
    4. Return a plain-text response.
    """
    existing = find_existing_threads(topic)
    if existing:
        return existing

    post_data = generate_forum_post(topic)
    title = post_data.get("title", f"Discussion: {topic}")
    body  = post_data.get("body", topic)
    cat   = _pick_category(topic)

    thread = save_forum_post(title, body, cat, COMMUNITY)
    if thread:
        return (
            f"New discussion created!\n\n"
            f"Title: {thread.title}\n"
            f"Category: {thread.category.name}\n"
            f"View it at: /thread/{thread.slug}/"
        )
    return f"Discussion topic: {title}\n\n{body}"
