"""
elimu_ai/tools/forum.py

Forum tool — ALL persistence via ElimuAPIClient HTTP calls.
Zero Django ORM imports. Zero django.conf imports.

The AI worker never touches the Django database directly.
All forum reads/writes flow through the authenticated REST API.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Dict, List, Optional

from elimu_ai.gemini import generate
from elimu_ai.personas import COMMUNITY
from elimu_ai.prompts import FORUM_POST_PROMPT

logger = logging.getLogger(__name__)


# ── Category mapping (pure logic — no Django) ─────────────────────────────────

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


def _simple_slug(title: str) -> str:
    """Generate a URL-safe slug from a title (no DB uniqueness check needed here)."""
    return re.sub(r"[^\w-]", "-", title.lower())[:60]


# ── Gemini-based content generation ──────────────────────────────────────────

def generate_forum_post(topic: str) -> Dict[str, str]:
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
    logger.warning("forum: could not parse JSON from Gemini — using plain fallback.")
    return {"title": f"Discussion: {topic}", "body": raw.strip()}


# ── HTTP-based forum operations ───────────────────────────────────────────────

def find_existing_threads(topic: str) -> Optional[str]:
    """
    Search existing forum threads via HTTP API.
    Returns formatted text if matches found, None otherwise.
    Does NOT import Django.
    """
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        data = client.search_threads(query=topic, limit=3)
        threads = data.get("results") or data.get("threads") or []
        if not threads:
            return None

        lines = [
            "There are already some great discussions about this on ElimuTalks:",
            "",
        ]
        for t in threads:
            title    = t.get("title", "")
            slug     = t.get("slug", _simple_slug(title))
            category = t.get("category_name", "")
            lines.append(f"- {title}")
            if category:
                lines.append(f"  Category: {category}")
            lines.append(f"  /thread/{slug}/")
            lines.append("")
        lines.append("You can start a new thread if you have a different angle on this topic.")
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("forum.find_existing_threads: Django API unavailable — %s", exc)
        return None


def save_forum_post(
    title: str,
    body: str,
    category_slug: str,
    idempotency_key: Optional[str] = None,
) -> Optional[Dict]:
    """
    Create a forum discussion via HTTP API.
    Returns the created thread dict, or None if the API is unavailable.
    Idempotency-Key prevents duplicates on network retries.
    """
    key = idempotency_key or f"ai-discussion-{uuid.uuid5(uuid.NAMESPACE_URL, title).hex}"
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        result = client.create_discussion(
            title=title,
            body=body,
            category=category_slug,
            idempotency_key=key,
        )
        logger.info("forum: created discussion %r via API", title[:60])
        return result
    except Exception as exc:
        logger.warning("forum.save_forum_post: Django API unavailable — %s", exc)
        return None


def create_discussion(topic: str) -> str:
    """
    Create or find a community discussion.
    1. Check for existing threads via API.
    2. Generate post content with Gemini.
    3. Save via API.
    4. Return plain-text result (with link if saved).
    """
    existing = find_existing_threads(topic)
    if existing:
        return existing

    post_data = generate_forum_post(topic)
    title = post_data.get("title", f"Discussion: {topic}")
    body  = post_data.get("body", topic)
    cat   = _pick_category(topic)

    thread = save_forum_post(title, body, cat)
    if thread:
        slug = thread.get("slug") or _simple_slug(title)
        cat_name = thread.get("category_name", cat)
        return (
            f"New discussion created!\n\n"
            f"Title: {title}\n"
            f"Category: {cat_name}\n"
            f"View it at: /thread/{slug}/"
        )
    # API unavailable — return the generated content for graceful degradation
    return f"Discussion topic: {title}\n\n{body}"


def get_unanswered_threads(
    cutoff_hours: int = 3,
    page: int = 1,
    page_size: int = 50,
) -> List[Dict]:
    """
    Fetch unanswered forum threads from Django via HTTP.
    Returns a list of thread dicts or [] if API is unavailable.
    """
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        data = client.get_unanswered_threads(
            cutoff_hours=cutoff_hours,
            page=page,
            page_size=page_size,
        )
        return data.get("results") or data.get("threads") or []
    except Exception as exc:
        logger.warning("forum.get_unanswered_threads: Django API unavailable — %s", exc)
        return []


def post_ai_answer(
    thread_id: int,
    content: str,
    idempotency_key: Optional[str] = None,
) -> bool:
    """
    Post an AI-generated answer to a thread via HTTP API.
    Returns True on success, False if API unavailable.
    The idempotency key prevents duplicate posts on retry.
    """
    key = idempotency_key or f"ai-forum-answer-{thread_id}"
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        client.post_answer(thread_id=thread_id, content=content, idempotency_key=key)
        logger.info("forum.post_ai_answer: answered thread %d", thread_id)
        return True
    except Exception as exc:
        logger.warning("forum.post_ai_answer: failed for thread %d — %s", thread_id, exc)
        return False


def check_django_available() -> bool:
    """
    Lightweight Django health check via HTTP.
    Returns True if the Django API is reachable, False otherwise.
    NEVER imports Django.
    """
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        resp = client.api_health()
        return resp.get("status") in ("ok", "healthy", True)
    except Exception:
        return False
