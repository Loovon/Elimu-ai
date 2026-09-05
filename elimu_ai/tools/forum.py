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
from elimu_ai.tools.moderation import validate_generated_content

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

def generate_forum_post(topic: str) -> Optional[Dict[str, str]]:
    """
    Ask Gemini to generate a forum post for the topic.
    Returns {title: str, body: str} only when safe content is produced.
    """
    prompt = FORUM_POST_PROMPT.format(topic=topic)
    raw = generate(prompt)
    if not validate_generated_content(raw, context="forum-generation"):
        logger.warning("forum: generated content rejected as anomalous for topic=%r", topic)
        try:
            from elimu_ai.agents.learning import LearningAgent
            LearningAgent().record_failure(
                question=topic,
                intents=["forum_generation"],
                tools_used=["gemini", "forum"],
                failure_reason="generated content rejected as anomalous",
            )
        except Exception:
            pass
        return None

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            title = str(data.get("title", f"Discussion: {topic}")).strip()
            body = str(data.get("body", raw)).strip()
            if not validate_generated_content(title + "\n" + body, context="forum-json"):
                return None
            return {"title": title, "body": body}
        except Exception:
            pass
    logger.warning("forum: could not parse JSON from Gemini — using plain fallback.")
    fallback = {"title": f"Discussion: {topic}", "body": raw.strip()}
    if not validate_generated_content(fallback["title"] + "\n" + fallback["body"], context="forum-plain"):
        return None
    return fallback


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
    persona_key: Optional[str] = None,
) -> Optional[Dict]:
    """
    Create a forum discussion via HTTP API.
    Returns the created thread dict, or None if the API is unavailable.
    Idempotency-Key prevents duplicates on network retries.

    persona_key (optional): stable named-persona identifier sent to Django
    so the thread author is correctly attributed.
    """
    combined = f"{title}\n{body}"
    if not validate_generated_content(combined, context="discussion-publication"):
        logger.warning("forum.save_forum_post: rejected publication for persona=%s due to anomalous content", persona_key or "none")
        try:
            from elimu_ai.agents.learning import LearningAgent
            LearningAgent().record_failure(
                question=title,
                intents=["forum_publication"],
                tools_used=["forum", "http_client"],
                failure_reason="rejected discussion before API publication",
            )
        except Exception:
            pass
        return None

    key = idempotency_key or f"ai-discussion-{uuid.uuid5(uuid.NAMESPACE_URL, title).hex}"
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        payload = {
            "title": title,
            "body": body,
            "category": category_slug,
            "ai_generated": True,
        }
        if persona_key:
            payload.update(client._persona_fields(persona_key))
        result = client.create_discussion(
            title=title,
            body=body,
            category=category_slug,
            idempotency_key=key,
            persona_key=persona_key,
        )
        logger.info(
            "forum: created discussion %r persona=%s via API",
            title[:60], persona_key or "none",
        )
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
    if not post_data:
        logger.warning("forum.create_discussion: safe failure state for topic=%r", topic)
        return "Discussion generation failed. Please try again later."

    title = str(post_data.get("title", f"Discussion: {topic}")).strip()
    body  = str(post_data.get("body", topic)).strip()
    if not validate_generated_content(f"{title}\n{body}", context="discussion-content"):
        logger.warning("forum.create_discussion: rejected generated discussion content for topic=%r", topic)
        return "Discussion generation failed. Please try again later."

    cat = _pick_category(topic)
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
    persona_key: Optional[str] = None,
) -> bool:
    """
    Post an AI-generated answer to a thread via HTTP API.
    Returns True on success, False if API unavailable.
    The idempotency key prevents duplicate posts on retry.

    persona_key (optional): stable named-persona identifier sent to Django
    so the reply author is correctly attributed.
    """
    if not validate_generated_content(content, context="reply-publication"):
        logger.warning("forum.post_ai_answer: rejected publication for thread=%d persona=%s due to anomaly", thread_id, persona_key or "none")
        try:
            from elimu_ai.agents.learning import LearningAgent
            LearningAgent().record_failure(
                question=content[:200],
                intents=["forum_reply"],
                tools_used=["forum", "http_client"],
                failure_reason="rejected reply before API publication",
            )
        except Exception:
            pass
        return False

    key = idempotency_key or f"ai-forum-answer-{thread_id}"
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        client.post_answer(
            thread_id=thread_id,
            content=content,
            idempotency_key=key,
            persona_key=persona_key,
        )
        logger.info(
            "forum.post_ai_answer: answered thread %d persona=%s",
            thread_id, persona_key or "none",
        )
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


# ── Thread discovery (semantic-aware) ────────────────────────────────────────

def find_relevant_existing_thread(
    topic: str,
    similarity_threshold: float = 0.3,
) -> Optional[Dict]:
    """
    Find the most semantically relevant existing forum thread for a topic.

    Returns the best-matching thread dict if found (with keys: id, title,
    slug, post_count, category_name), or None if no relevant thread exists.

    This prevents creating duplicate discussions when a suitable one exists.
    Uses title-word overlap as a lightweight semantic signal (no Gemini call).
    """
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        data = client.search_threads(query=topic, limit=10)
        threads = data.get("results") or data.get("threads") or []
        if not threads:
            return None

        topic_words = set(w.lower() for w in topic.split() if len(w) > 3)
        # Remove stop words
        _STOP = {"what", "which", "that", "this", "with", "have", "does",
                 "should", "would", "could", "about", "from", "your", "their",
                 "they", "them", "when", "where", "will", "been", "more",
                 "most", "some", "very", "just", "also", "only", "much"}
        topic_words -= _STOP
        if not topic_words:
            return None

        best_thread = None
        best_score = 0.0

        for t in threads:
            title = t.get("title", "")
            title_words = set(w.lower() for w in title.split() if len(w) > 3)
            title_words -= _STOP
            if not title_words:
                continue
            shared = topic_words & title_words
            score = len(shared) / max(len(topic_words), len(title_words))
            if score > best_score:
                best_score = score
                best_thread = t

        if best_thread and best_score >= similarity_threshold:
            logger.info(
                "forum.find_relevant_existing_thread: found match %r "
                "(score=%.2f) for topic=%r",
                best_thread.get("title", "")[:60],
                best_score,
                topic[:60],
            )
            return best_thread

        return None

    except Exception as exc:
        logger.warning("forum.find_relevant_existing_thread: %s", exc)
        return None


def get_active_threads_for_growth(
    min_posts: int = 2,
    max_posts: int = 29,
    limit: int = 10,
) -> List[Dict]:
    """
    Fetch threads that are active but have not yet reached the growth target.
    Returns threads suitable for AI continuation.
    """
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        data = client.get_active_threads(
            min_posts=min_posts,
            max_posts=max_posts,
            limit=limit,
        )
        return data.get("results") or data.get("threads") or []
    except Exception as exc:
        logger.warning("forum.get_active_threads_for_growth: %s", exc)
        return []


def get_thread_context(thread_id: int) -> Optional[Dict]:
    """
    Fetch full thread context (title, posts, category) for a given thread ID.
    Returns None if the API is unavailable.
    """
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        return client.get_thread_detail(thread_id)
    except Exception as exc:
        logger.warning("forum.get_thread_context: thread=%d error=%s", thread_id, exc)
        return None


def post_moderated_reply(
    thread_id: int,
    content: str,
    persona_name: str = "community",
    idempotency_key: Optional[str] = None,
    persona_key: Optional[str] = None,
) -> bool:
    """
    Post a reply to an existing thread AFTER passing local moderation.
    Returns True on success, False if moderation fails or API is unavailable.

    persona_key (optional): if provided, passed to Django to attribute the
    reply to the correct named AI persona rather than a generic AI user.

    This is the safe posting path for all AI-generated content:
      1. Local moderation check
      2. Django API moderation check (best-effort)
      3. Post via HTTP with persona identity
    """
    from elimu_ai.tools.moderation import moderate

    # Layer 1: local moderation
    local_result = moderate(content)
    if local_result != "Content approved.":
        logger.warning(
            "forum.post_moderated_reply: local moderation blocked post to thread %d: %s",
            thread_id, local_result,
        )
        return False

    # Layer 2: Django API moderation (best-effort, never blocks if API down)
    try:
        from elimu_ai.http_client import get_client
        client = get_client()
        mod_result = client.check_moderation(content)
        approved = mod_result.get("approved", True)
        if not approved:
            action = mod_result.get("action", "")
            logger.warning(
                "forum.post_moderated_reply: Django moderation blocked post to thread %d "
                "(action=%s)", thread_id, action,
            )
            return False
    except Exception as exc:
        logger.debug(
            "forum.post_moderated_reply: Django moderation check failed (non-fatal): %s", exc
        )
        # Continue — local moderation already passed

    # Layer 3: post reply with persona identity
    return post_ai_answer(
        thread_id,
        content,
        idempotency_key=idempotency_key,
        persona_key=persona_key,
    )
