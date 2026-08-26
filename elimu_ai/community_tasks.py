"""
elimu_ai/community_tasks.py

All autonomous community participation tasks.
Zero Django ORM. All forum operations go through HTTP.

Functions:
  select_thread_by_priority(threads)  — deterministic, fewest-posts-first
  task_main_persona_community()       — parent/teacher/student role rotation
  get_role_last_activity(repo, role)  — LRU role detection
  select_persona_for_role(repo, role) — named persona within a role
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def _tokenize_text(value: str) -> set[str]:
    """Normalize text into a lightweight token set for similarity checks."""
    if not value:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2
    }


def is_near_duplicate(candidate: str, recent_items: Sequence[str], threshold: float = 0.72) -> bool:
    """Return True if a candidate looks too similar to a recent message."""
    candidate_tokens = _tokenize_text(candidate)
    if not candidate_tokens:
        return False

    for recent in recent_items:
        recent_tokens = _tokenize_text(str(recent))
        if not recent_tokens:
            continue
        shared = len(candidate_tokens & recent_tokens)
        if shared == 0:
            continue
        union = len(candidate_tokens | recent_tokens)
        score = shared / union if union else 0.0
        if score >= threshold:
            return True
    return False


def should_post(
    *,
    function_cooldown_ready: bool,
    persona_cooldown_ready: bool,
    not_duplicate: bool,
    under_daily_cap: bool,
    under_per_thread_cap: bool,
) -> Tuple[bool, str]:
    """Central governance gate for posting.

    All relevant gates must be open, combined with AND semantics. The returned
    reason is suitable for logs or debug output.
    """
    checks = [
        (function_cooldown_ready, "function cooldown"),
        (persona_cooldown_ready, "persona cooldown"),
        (not_duplicate, "duplicate"),
        (under_daily_cap, "daily cap"),
        (under_per_thread_cap, "per-thread cap"),
    ]
    for is_open, label in checks:
        if not is_open:
            return False, f"blocked: {label}"
    return True, "allowed"


def evaluate_post_gate(
    *,
    repo,
    persona_key: Optional[str],
    candidate_text: str,
    function_cooldown_seconds: int,
    persona_cooldown_seconds: int,
    recent_items: Optional[Sequence[str]] = None,
    under_daily_cap: bool = True,
    thread_post_count: Optional[int] = None,
    per_thread_cap: Optional[int] = None,
) -> Tuple[bool, str]:
    """Compute a single post decision using the shared governance gate."""
    recent_items = list(recent_items or [])

    function_cooldown_ready = True
    if function_cooldown_seconds > 0:
        try:
            function_cooldown_ready = repo.seconds_since_last_safe() is None or repo.seconds_since_last_safe() >= function_cooldown_seconds
        except Exception:
            function_cooldown_ready = True

    persona_cooldown_ready = True
    if persona_key:
        try:
            secs = repo.seconds_since_persona_last_posted_safe(persona_key)
            persona_cooldown_ready = secs is None or secs >= persona_cooldown_seconds
        except Exception:
            persona_cooldown_ready = True

    not_duplicate = not is_near_duplicate(candidate_text, recent_items)

    if thread_post_count is not None and per_thread_cap is not None:
        under_per_thread_cap = thread_post_count < per_thread_cap
    else:
        under_per_thread_cap = True

    return should_post(
        function_cooldown_ready=function_cooldown_ready,
        persona_cooldown_ready=persona_cooldown_ready,
        not_duplicate=not_duplicate,
        under_daily_cap=bool(under_daily_cap),
        under_per_thread_cap=under_per_thread_cap,
    )

# The three main community roles
MAIN_ROLES = ("parent", "teacher", "student")


# ---------------------------------------------------------------------------
# Thread prioritization
# ---------------------------------------------------------------------------

def _get_post_count(thread: Dict) -> Optional[int]:
    """Robustly extract post count from a thread dict."""
    for field in ("post_count", "posts_count", "num_posts", "reply_count"):
        val = thread.get(field)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    posts = thread.get("posts")
    if isinstance(posts, list):
        return len(posts)
    return None


def _get_last_activity(thread: Dict) -> str:
    """Return a sortable timestamp string for the thread's last activity."""
    for field in ("last_activity", "latest_post_at", "updated_at", "created_at"):
        val = thread.get(field)
        if val:
            return str(val)
    lp = thread.get("latest_post")
    if isinstance(lp, dict):
        return str(lp.get("created_at", ""))
    return ""


def select_thread_by_priority(threads: List[Dict]) -> Optional[Dict]:
    """
    Select the highest-priority thread for continuation.

    Priority order (deterministic — no randomness):
      1. Lowest post count  (fewest replies first)
      2. Oldest last activity (least recently active)
      3. Oldest creation time

    This ensures Thread A (2 posts) is always chosen over Thread B (5 posts)
    and over Thread C (17 posts).

    Only uses randomness when candidates are genuinely equal on ALL criteria,
    which in practice should be extremely rare.
    """
    if not threads:
        return None

    valid = [
        t for t in threads
        if t.get("id") and t.get("title", "").strip() and _get_post_count(t) is not None
    ]
    if not valid:
        return None

    # Sort by (post_count ASC, last_activity ASC, created_at ASC)
    def sort_key(t: Dict):
        pc = _get_post_count(t)
        last = _get_last_activity(t)
        created = str(t.get("created_at", ""))
        return (pc, last, created)

    valid.sort(key=sort_key)

    selected = valid[0]
    logger.info(
        "community: thread priority selected id=%s title=%r post_count=%s",
        selected.get("id"), selected.get("title", "")[:60], _get_post_count(selected),
    )
    return selected


# ---------------------------------------------------------------------------
# Role rotation — LRU across parent / teacher / student
# ---------------------------------------------------------------------------

def get_role_last_activity(repo, role: str) -> Optional[float]:
    """
    Return seconds since any persona in this role last posted.
    Returns None if no activity recorded.
    """
    from elimu_ai.personas.named import get_personas_by_category
    personas = get_personas_by_category(role)
    if not personas:
        return None

    oldest: Optional[float] = None
    for p in personas:
        secs = repo.seconds_since_persona_last_posted_safe(p.key)
        if secs is None:
            # Never posted — treat as very old (highest priority)
            return float("inf")
        if oldest is None or secs > oldest:
            oldest = secs
    return oldest


def select_role_lru(repo) -> str:
    """
    Select the main role (parent/teacher/student) that has been least
    recently active. Uses LRU logic across all personas in each role.

    Returns one of: "parent", "teacher", "student"
    """
    role_activity: Dict[str, Optional[float]] = {}
    for role in MAIN_ROLES:
        role_activity[role] = get_role_last_activity(repo, role)

    logger.info(
        "community: role activity — parent=%.0fs teacher=%.0fs student=%.0fs",
        role_activity.get("parent") or 0,
        role_activity.get("teacher") or 0,
        role_activity.get("student") or 0,
    )

    # Sort by activity: None (never) → float("inf") → highest secs first
    def role_sort_key(role: str) -> float:
        v = role_activity.get(role)
        if v is None:
            return float("inf")
        return v

    selected = max(MAIN_ROLES, key=role_sort_key)
    logger.info("community: selected role=%s (least recently active)", selected)
    return selected


def select_persona_for_role(repo, role: str, persona_cooldown: int) -> Optional[Tuple[str, str]]:
    """
    Select the least-recently-used named persona within a role category.

    Returns (persona_key, display_name) or None if no eligible persona.
    """
    from elimu_ai.personas.named import get_personas_by_category

    personas = get_personas_by_category(role)
    if not personas:
        logger.warning("community: no personas found for role=%s", role)
        return None

    candidates = []
    for p in personas:
        secs = repo.seconds_since_persona_last_posted_safe(p.key)
        if secs is None:
            candidates.append((p, float("inf")))
        elif secs >= persona_cooldown:
            candidates.append((p, secs))

    if candidates:
        # Never-used personas first — but if multiple, pick oldest
        never_used = [c for c in candidates if c[1] == float("inf")]
        if never_used:
            import random as _r
            p = _r.choice(never_used)[0]
            logger.info(
                "community: first-time persona role=%s key=%s display=%s",
                role, p.key, p.display_name,
            )
            return p.key, p.display_name

        # LRU: pick the one with the highest elapsed time
        p, secs = max(candidates, key=lambda x: x[1])
        logger.info(
            "community: LRU persona role=%s key=%s display=%s secs_since=%.0f",
            role, p.key, p.display_name, secs,
        )
        return p.key, p.display_name

    # All on cooldown — pick the one that posted longest ago as fallback
    fallback = []
    for p in personas:
        secs = repo.seconds_since_persona_last_posted_safe(p.key)
        if secs is not None:
            fallback.append((p, secs))
    if fallback:
        p, secs = max(fallback, key=lambda x: x[1])
        logger.info(
            "community: all on cooldown fallback role=%s key=%s secs=%.0f",
            role, p.key, secs,
        )
        return p.key, p.display_name

    # Last resort: first persona in role
    p = personas[0]
    return p.key, p.display_name


# ---------------------------------------------------------------------------
# Main community task — parent/teacher/student rotation
# ---------------------------------------------------------------------------

def task_main_persona_community() -> str:
    """
    Dedicated parent/teacher/student rotation community task.

    Every run:
      1. Selects the ROLE (parent/teacher/student) that participated least recently.
      2. Selects the PERSONA within that role via LRU.
      3. Finds the lowest-reply eligible thread.
      4. Generates and posts a reply in persona voice.
      5. Logs role + persona + thread for observability.

    This is separate from task_generate_discussions which handles proactive
    thread creation. This task focuses purely on community participation.
    """
    from elimu_ai.config import (
        PERSONA_COOLDOWN,
        THREAD_MIN_POSTS_FOR_CONTINUATION,
        THREAD_GROWTH_TARGET,
    )

    repo = _get_repo()

    # Step 1: Select role via LRU
    role = select_role_lru(repo)

    # Step 2: Select persona within role
    persona_result = select_persona_for_role(repo, role, PERSONA_COOLDOWN)
    if not persona_result:
        logger.warning(
            "community: no eligible persona for role=%s — skipping", role
        )
        return f"skipped: no eligible persona for role={role}"

    persona_key, persona_display = persona_result

    logger.info(
        "community: action=participate role=%s persona=%s display=%s",
        role, persona_key, persona_display,
    )

    # Step 3: Find the thread with the fewest posts (priority ordering)
    from elimu_ai.tools.forum import get_active_threads_for_growth, get_unanswered_threads

    # First check for unanswered threads (post_count == 1)
    unanswered = get_unanswered_threads(cutoff_hours=6)
    unanswered_eligible = [t for t in unanswered if _get_post_count(t) == 1]

    if unanswered_eligible:
        thread = select_thread_by_priority(unanswered_eligible)
        action = "answer_unanswered"
    else:
        # Fall back to lowest-reply active threads
        active = get_active_threads_for_growth(
            min_posts=THREAD_MIN_POSTS_FOR_CONTINUATION,
            max_posts=THREAD_GROWTH_TARGET - 1,
            limit=20,
        )
        thread = select_thread_by_priority(active)
        action = "participate"

    if not thread:
        logger.info(
            "community: no eligible thread for role=%s persona=%s — skipping",
            role, persona_key,
        )
        return f"skipped: no eligible thread for role={role} persona={persona_key}"

    thread_id    = thread.get("id")
    thread_title = thread.get("title", "")
    post_count   = _get_post_count(thread)

    logger.info(
        "community: action=%s thread=%d %r post_count=%s role=%s persona=%s",
        action, thread_id, thread_title[:60], post_count, role, persona_key,
    )

    # Step 4: Generate and post reply in persona voice
    result = _post_as_persona(
        thread_id=thread_id,
        thread_title=thread_title,
        persona_key=persona_key,
        persona_display=persona_display,
    )

    if result:
        # Log to proactive discussion history for LRU tracking
        try:
            repo.log_discussion(
                persona=persona_key,
                topic=thread_title,
                status="continued_existing_thread",
                thread_id=thread_id,
            )
        except Exception as log_exc:
            logger.warning("community: history logging failed: %s", log_exc)

        logger.info(
            "community: POSTED action=%s thread=%d persona=%s role=%s",
            action, thread_id, persona_key, role,
        )
        return (
            f"posted: action={action} thread={thread_id} "
            f"role={role} persona={persona_key} posts={post_count}"
        )
    else:
        logger.warning(
            "community: post failed action=%s thread=%d persona=%s",
            action, thread_id, persona_key,
        )
        return f"failed: action={action} thread={thread_id} persona={persona_key}"


def _get_repo():
    from elimu_ai.db.repositories import ProactiveDiscussionRepository
    return ProactiveDiscussionRepository()


def _post_as_persona(
    thread_id: int,
    thread_title: str,
    persona_key: str,
    persona_display: str,
) -> bool:
    """Generate and post a reply as the named persona."""
    from elimu_ai.tools.forum import post_moderated_reply
    from elimu_ai.gemini import generate as gemini_generate
    from elimu_ai.personas.named import get_persona
    import uuid

    persona = get_persona(persona_key)
    if persona is None:
        logger.error("community: unknown persona key=%r", persona_key)
        return False

    prompt = (
        f"{persona.voice}\n\n"
        f"Your role: {persona.role}. Your register: {persona.role_category}. "
        f"Your perspective: {persona.bio}.\n"
        f"Write as {persona.display_name}, not as a generic AI assistant. "
        f"Keep the voice distinct, grounded, and authentic to this person.\n\n"
        f"Forum discussion title: {thread_title}\n\n"
        "Write a helpful, genuine reply to this discussion.\n"
        "Rules:\n"
        "- Plain text only, no Markdown.\n"
        "- 2-4 sentences maximum.\n"
        "- Sound like a real community member, not a robot.\n"
        "- Act from this persona's role, register, and lived perspective.\n"
        "- Add real value: answer a question, share an insight, or invite others.\n"
        "- No greetings like 'Hello everyone'."
    )

    ikey = f"main-persona-{thread_id}-{persona_key}-{uuid.uuid4().hex[:8]}"

    try:
        reply = gemini_generate(prompt)
        if not reply or reply.startswith("Elimu AI") or reply.startswith("Gemini error"):
            logger.warning("community: empty/invalid reply for persona=%s", persona_key)
            return False
        reply = reply.strip()
        if len(reply) < 20:
            return False

        return post_moderated_reply(
            thread_id=thread_id,
            content=reply,
            persona_name=persona_key,
            idempotency_key=ikey,
            persona_key=persona_key,
        )
    except Exception as exc:
        logger.error("community: _post_as_persona failed persona=%s: %s", persona_key, exc)
        return False
