"""
elimu_ai/tools/forum.py

Forum tool — Django-aware thread creation and search.
Responsibilities:
  - generate_forum_post(topic)          → dict {title, body}  (uses Gemini)
  - save_forum_post(title, body, ...)   → Thread | None       (uses Django ORM)
  - create_discussion(topic)            → str                  (orchestrates both)
  - find_existing_threads(topic)        → str | None

Rules:
  - Django ORM calls are isolated in this file only.
  - Never imports service.py.
  - Gracefully handles missing Django setup.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from elimu_ai.gemini import generate
from elimu_ai.prompts import FORUM_POST_PROMPT
from elimu_ai.personas import COMMUNITY


# ── Helpers ───────────────────────────────────────────────────────────────────

def _django_available() -> bool:
    try:
        import django
        from django.conf import settings
        return settings.configured
    except Exception:
        return False


def _unique_slug(title: str) -> str:
    """Generate a slug unique within the Thread table."""
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
        import re as _re
        return _re.sub(r"[^\w-]", "-", title.lower())[:60]


def _pick_category(topic: str) -> str:
    """Map topic keywords to a forum category slug."""
    lower = topic.lower()
    if "kcse" in lower or "exam" in lower:
        return "kcse"
    if "cbc" in lower:
        return "cbc"
    if "teacher" in lower or "classroom" in lower:
        return "teachers"
    if "parent" in lower or "family" in lower:
        return "parents"
    return "revision"


# ── Core functions ────────────────────────────────────────────────────────────

def generate_forum_post(topic: str) -> dict:
    """
    Ask Gemini to generate a forum post for the given topic.
    Returns a dict {title: str, body: str}.
    """
    prompt = FORUM_POST_PROMPT.format(topic=topic)
    raw = generate(prompt)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {"title": f"Discussion: {topic}", "body": raw.strip()}


def save_forum_post(
    title: str,
    body: str,
    category_slug: str,
    persona: str = COMMUNITY,
) -> Optional[object]:
    """
    Save a forum thread + opening post to the Django database.
    Returns the Thread object or None if Django is unavailable.
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
        return thread
    except Exception:
        return None


def find_existing_threads(topic: str) -> Optional[str]:
    """
    Search existing Django forum threads for threads related to the topic.
    Returns a formatted string if matches found, None otherwise.
    """
    if not _django_available():
        return None
    try:
        from django.db.models import Q
        from forum.models import Thread

        keywords = [w for w in topic.lower().split() if len(w) > 3]
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
        lines.append("You can also start a new thread if you have a different angle on this topic.")
        return "\n".join(lines)
    except Exception:
        return None


def create_discussion(topic: str) -> str:
    """
    1. Check for existing related threads — recommend them if found.
    2. Otherwise generate and save a new thread.
    Returns a plain-text response string.
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
    # Django unavailable — return the generated content as plain text
    return f"Discussion topic: {title}\n\n{body}"
