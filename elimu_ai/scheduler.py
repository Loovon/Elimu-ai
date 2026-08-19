"""
elimu_ai/scheduler.py — Autonomous background scheduler (APScheduler 3.x).

ZERO Django ORM imports. All forum/catalog ops go through HTTP.
Must run independently — Django being down must not crash any task.
Each task catches its own exceptions and returns a status string.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from elimu_ai.config import (
    SCHEDULER_ANSWER_INTERVAL,
    SCHEDULER_CATALOG_INTERVAL,
    SCHEDULER_DISCUSS_INTERVAL,
    SCHEDULER_MODERATE_INTERVAL,
    SCHEDULER_RECOMMEND_INTERVAL,
    SCHEDULER_RETRY_FAILURES_INTERVAL,
    MAX_RETRY_ATTEMPTS,
    PROACTIVE_DISCUSSION_COOLDOWN,
    MAX_PROACTIVE_DISCUSSIONS_PER_DAY,
    PERSONA_COOLDOWN,
    THREAD_GROWTH_TARGET,
    THREAD_MIN_POSTS_FOR_CONTINUATION,
    THREAD_CONTINUATION_COOLDOWN,
    SCHEDULER_ARTICLE_INTERVAL,
    MAX_ARTICLES_PER_DAY,
)

logger = logging.getLogger(__name__)

scheduler_status: Dict[str, Any] = {
    "running":    False,
    "started_at": None,
    "last_run":   {},
    "errors":     {},
}

# ── Guard: prevent multiple scheduler instances in same process ──────────────
_scheduler_instance: Optional[Any] = None
_scheduler_lock = threading.Lock()


# ── Tasks — all HTTP-based, zero Django imports ───────────────────────────────

def task_answer_unanswered() -> str:
    try:
        from elimu_ai.tools.answer import answer_unanswered_threads
        count = answer_unanswered_threads()
        return f"Answered {count} threads."
    except Exception as exc:
        logger.error("task_answer_unanswered: %s", exc)
        return f"Error: {exc}"


def task_generate_discussions() -> str:
    """
    Autonomous community discussion generator.

    Decision flow (agentic):
      1. Check for unanswered threads (post_count == 1) → answer them
      2. Check for active threads below THREAD_GROWTH_TARGET → continue one
      3. Proactive generation with forum-discovery guard:
         a. Search existing threads for topic before creating
         b. If relevant thread found → continue it instead
         c. Rate-limit / cooldown / duplicate checks
         d. Create new discussion in persona voice

    The existing answer_unanswered workflow is untouched.
    All logging goes to ai_scheduler_log via the standard _make_job wrapper.
    """
    from elimu_ai.tools.forum import get_unanswered_threads
    from elimu_ai.config import (
        PROACTIVE_DISCUSSION_COOLDOWN,
        MAX_PROACTIVE_DISCUSSIONS_PER_DAY,
        PERSONA_COOLDOWN,
    )

    try:
        # ── STEP 1: unanswered threads exist → answer them ─────────────────
        threads = get_unanswered_threads(cutoff_hours=3)
        answerable = [t for t in threads
                      if t.get("post_count", t.get("posts_count", 0)) == 1]

        if answerable:
            from elimu_ai.tools.answer import answer_unanswered_threads
            count = answer_unanswered_threads()
            logger.info(
                "generate_discussions: mode=response answered=%d threads", count
            )
            return f"answered_existing_thread: {count} threads answered"

        # ── STEP 2: continue active threads below growth target ────────────
        continuation_result = _try_continue_existing_thread()
        if continuation_result:
            logger.info(
                "generate_discussions: mode=continue result=%r", continuation_result[:80]
            )
            return continuation_result

        # ── STEP 3: proactive generation ───────────────────────────────────
        logger.info(
            "generate_discussions: mode=proactive reason=no_unanswered_threads"
        )

        repo = _get_proactive_repo()

        # Guard: daily limit
        today_count = repo.count_today_safe()
        if today_count >= MAX_PROACTIVE_DISCUSSIONS_PER_DAY:
            logger.info(
                "generate_discussions: proactive generation skipped — "
                "daily limit reached (%d/%d)",
                today_count, MAX_PROACTIVE_DISCUSSIONS_PER_DAY,
            )
            return f"skipped_cooldown: daily limit {today_count}/{MAX_PROACTIVE_DISCUSSIONS_PER_DAY}"

        # Guard: global cooldown
        secs = repo.seconds_since_last_safe()
        if secs is not None and secs < PROACTIVE_DISCUSSION_COOLDOWN:
            remaining = int(PROACTIVE_DISCUSSION_COOLDOWN - secs)
            logger.info(
                "generate_discussions: proactive generation skipped — "
                "cooldown active (%ds remaining)", remaining,
            )
            return f"skipped_cooldown: {remaining}s remaining"

        # Select persona
        persona_name, persona_display = _select_persona(repo, PERSONA_COOLDOWN)
        logger.info(
            "generate_discussions: mode=proactive persona=%s", persona_name
        )

        # Select topic
        recent_topics = repo.get_recent_topics_safe(limit=15)
        topic = _select_topic(persona_name, recent_topics)
        if not topic:
            logger.warning(
                "generate_discussions: proactive generation failed: "
                "could not select a non-duplicate topic"
            )
            repo.log_discussion(
                persona=persona_name, topic="", status="skipped_duplicate"
            )
            return "skipped_duplicate: no fresh topic available"

        # ── Forum discovery guard — search before creating ─────────────────
        # If a highly relevant existing thread already exists, continue it
        # instead of spawning a brand-new discussion.
        existing_thread = _find_relevant_thread_for_topic(topic)
        if existing_thread:
            thread_id    = existing_thread.get("id")
            thread_title = existing_thread.get("title", "")
            thread_posts = existing_thread.get("post_count",
                           existing_thread.get("posts_count", 0))

            if thread_id and thread_posts < THREAD_GROWTH_TARGET:
                cont_result = _post_continuation_reply(
                    thread_id=thread_id,
                    thread_title=thread_title,
                    persona_name=persona_name,
                    topic_context=topic,
                )
                if cont_result:
                    repo.log_discussion(
                        persona=persona_name,
                        topic=f"[continuation] {thread_title}",
                        status="created_proactive_discussion",
                    )
                    logger.info(
                        "generate_discussions: continued existing thread=%d "
                        "instead of creating new persona=%s",
                        thread_id, persona_name,
                    )
                    return (
                        f"created_proactive_discussion: continued existing thread "
                        f"id={thread_id} persona={persona_name}"
                    )

        logger.info(
            "generate_discussions: mode=proactive persona=%s topic=%r "
            "action=create_discussion",
            persona_name, topic[:80],
        )

        # Create new discussion
        t0 = time.monotonic()
        try:
            result_text = _create_discussion_as_persona(persona_name, persona_display, topic)
            duration_ms = int((time.monotonic() - t0) * 1000)
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                "generate_discussions: proactive generation failed: %s", exc
            )
            repo.log_discussion(
                persona=persona_name, topic=topic,
                status="failed", duration_ms=duration_ms, error=str(exc),
            )
            return f"Error: proactive generation failed: {exc}"

        repo.log_discussion(
            persona=persona_name, topic=topic,
            status="created_proactive_discussion", duration_ms=duration_ms,
        )
        logger.info(
            "generate_discussions: proactive discussion created successfully "
            "persona=%s topic=%r ms=%d", persona_name, topic[:80], duration_ms,
        )
        return f"created_proactive_discussion: persona={persona_name} topic={topic[:60]}"

    except Exception as exc:
        logger.error("task_generate_discussions: %s", exc)
        return f"Error: {exc}"


# ── Proactive discussion helpers ──────────────────────────────────────────────

def _get_proactive_repo():
    """Return a ProactiveDiscussionRepository, always available."""
    from elimu_ai.db.repositories import ProactiveDiscussionRepository
    return ProactiveDiscussionRepository()


def _find_relevant_thread_for_topic(topic: str) -> Optional[Dict]:
    """
    Search existing forum threads for a topic before creating a new discussion.
    Returns the best-matching thread if found with similarity >= 0.4, else None.
    Prevents duplicate discussions when a suitable one already exists.
    """
    try:
        from elimu_ai.tools.forum import find_relevant_existing_thread
        return find_relevant_existing_thread(topic, similarity_threshold=0.4)
    except Exception as exc:
        logger.debug("_find_relevant_thread_for_topic: %s", exc)
        return None


def _try_continue_existing_thread() -> Optional[str]:
    """
    Look for active threads below the growth target and post a meaningful reply.
    Returns a result string if a continuation was posted, else None.
    """
    try:
        from elimu_ai.tools.forum import get_active_threads_for_growth
        from elimu_ai.config import (
            THREAD_GROWTH_TARGET,
            THREAD_MIN_POSTS_FOR_CONTINUATION,
            THREAD_CONTINUATION_COOLDOWN,
            PERSONA_COOLDOWN,
        )

        threads = get_active_threads_for_growth(
            min_posts=THREAD_MIN_POSTS_FOR_CONTINUATION,
            max_posts=THREAD_GROWTH_TARGET - 1,
            limit=5,
        )
        if not threads:
            return None

        # Pick the first thread (most recently active by default from API)
        repo = _get_proactive_repo()
        persona_name, _ = _select_persona(repo, PERSONA_COOLDOWN)

        for thread in threads:
            thread_id    = thread.get("id")
            thread_title = thread.get("title", "")
            post_count   = thread.get("post_count", thread.get("posts_count", 0))
            if not thread_id or not thread_title:
                continue

            result = _post_continuation_reply(
                thread_id=thread_id,
                thread_title=thread_title,
                persona_name=persona_name,
                topic_context=thread_title,
            )
            if result:
                logger.info(
                    "generate_discussions: continued thread=%d posts=%d/%d persona=%s",
                    thread_id, post_count, THREAD_GROWTH_TARGET, persona_name,
                )
                return (
                    f"continued_existing_thread: id={thread_id} "
                    f"posts={post_count}/{THREAD_GROWTH_TARGET} "
                    f"persona={persona_name}"
                )

        return None

    except Exception as exc:
        logger.debug("_try_continue_existing_thread: %s", exc)
        return None


def _post_continuation_reply(
    thread_id: int,
    thread_title: str,
    persona_name: str,
    topic_context: str = "",
) -> bool:
    """
    Generate and post a meaningful continuation reply to an existing thread.
    Uses moderation gate. Returns True if posted successfully.
    """
    from elimu_ai.tools.forum import post_moderated_reply
    from elimu_ai.gemini import generate as gemini_generate

    _CONTINUATION_VOICE = {
        "teacher":    "As an experienced Kenyan teacher, add a useful educational contribution to this discussion.",
        "student":    "As a Kenyan student, share a genuine perspective or question about this topic.",
        "community":  "As a community member, add a relevant point to keep this discussion going.",
        "counsellor": "As a career counsellor, provide practical guidance related to this topic.",
        "parent":     "As a Kenyan parent, share your perspective on this educational topic.",
        "librarian":  "As a librarian, suggest resources or additional information for this discussion.",
        "quizmaster": "As an exam preparation specialist, add a useful tip or question to this discussion.",
    }

    voice = _CONTINUATION_VOICE.get(
        persona_name,
        "Add a useful educational point to this discussion.",
    )
    context = topic_context or thread_title

    prompt = (
        f"{voice}\n\n"
        f"Discussion title: {thread_title}\n"
        f"Context: {context[:200]}\n\n"
        "Rules:\n"
        "- Plain text only, no Markdown.\n"
        "- 2-4 sentences maximum.\n"
        "- Sound like a genuine community member, not a robot.\n"
        "- Either answer a question, share an insight, or invite others to respond.\n"
        "- Do not just summarise the title — add real value.\n"
        "- No greetings like 'Hello everyone'."
    )

    import uuid
    ikey = f"continuation-{thread_id}-{persona_name}-{uuid.uuid4().hex[:8]}"

    try:
        reply = gemini_generate(prompt)
        if not reply or reply.startswith("Elimu AI") or reply.startswith("Gemini error"):
            return False
        reply = reply.strip()
        if len(reply) < 30:
            return False

        ok = post_moderated_reply(
            thread_id=thread_id,
            content=reply,
            persona_name=persona_name,
            idempotency_key=ikey,
        )
        return ok
    except Exception as exc:
        logger.debug("_post_continuation_reply: thread=%d error=%s", thread_id, exc)
        return False


def _select_persona(repo, persona_cooldown: int):
    """
    Choose a community-suitable persona from the existing registry.
    Rotate to avoid the same persona posting repeatedly.
    Returns (persona_name: str, persona_display: str).
    """
    from elimu_ai.personas.registry import persona_registry

    # Personas suitable for community discussion creation
    _COMMUNITY_PERSONAS = [
        "teacher", "student", "community", "counsellor", "parent",
        "librarian", "quizmaster",
    ]

    candidates = []
    for pname in _COMMUNITY_PERSONAS:
        cfg = persona_registry.get(pname)
        if cfg is None:
            continue
        secs = repo.seconds_since_persona_last_posted_safe(pname)
        if secs is None or secs >= persona_cooldown:
            candidates.append((pname, cfg.display))

    if not candidates:
        # All on cooldown — pick the one that posted longest ago
        best = _COMMUNITY_PERSONAS[0]
        best_cfg = persona_registry.get(best)
        return best, best_cfg.display if best_cfg else "CommunityAI"

    # Prefer the persona that hasn't posted most recently
    # (candidates list is ordered from registry; pick deterministically
    # but not always the first — rotate by day-of-year)
    idx = datetime.now(tz=timezone.utc).timetuple().tm_yday % len(candidates)
    pname, pdisplay = candidates[idx]
    return pname, pdisplay


# Educational topic pools keyed by persona
_PERSONA_TOPIC_POOLS: Dict[str, List[str]] = {
    "teacher": [
        "What is the most challenging CBC concept to teach and how do you handle it?",
        "Teachers: how do you make Mathematics engaging for learners who struggle?",
        "What preparation tips do you give students before KCSE?",
        "How do you use Elimu Library resources in your lesson plans?",
        "Teachers: what teaching strategy has improved student performance most?",
        "What is the most important skill Kenyan students need beyond exams?",
        "How do you handle mixed-ability classrooms in CBC?",
        "What Science experiment has worked best for illustrating a difficult concept?",
    ],
    "student": [
        "Which KCSE Mathematics topic do you find hardest and how do you tackle it?",
        "What study method actually worked for you during exam preparation?",
        "Students: how do you stay motivated when a subject feels impossible?",
        "Which revision resource helped you improve your grades the most?",
        "How do you balance school, revision, and extracurricular activities?",
        "What is the one tip you wish you knew before your first national exam?",
        "Which subject do you enjoy most and why?",
        "How do you use past papers to prepare for exams?",
    ],
    "community": [
        "What educational topic would you like Elimu AI to cover in more depth?",
        "How has digital learning changed education in your school?",
        "What does the ideal classroom look like for CBC learners?",
        "Parents and teachers: how can you better support learners at home?",
        "What is the biggest challenge facing education in Kenya today?",
        "How should schools prepare learners for a rapidly changing job market?",
        "Share a resource or study tip that has helped your community.",
    ],
    "counsellor": [
        "What career path are you considering after KCSE and why?",
        "How do you choose between university, college, and TVET after Form 4?",
        "What scholarship opportunities should Kenyan students know about?",
        "How important is subject choice in Form 1 for your future career?",
        "What advice would you give a student unsure about their career direction?",
    ],
    "parent": [
        "How do you support your child's learning at home under CBC?",
        "What resources do you use to help your child with holiday homework?",
        "Parents: what is the most difficult part of the CBC system for families?",
        "How do you keep your child motivated when they feel like giving up?",
        "What should schools do better to involve parents in learning?",
    ],
    "librarian": [
        "Which Elimu Library resources do you find most useful for revision?",
        "What is the best way to use schemes of work for self-study?",
        "Which subject notes are most popular on Elimu Library and why?",
        "How do past papers help students prepare more effectively?",
        "What CBC resources do teachers most need that are hard to find?",
    ],
    "quizmaster": [
        "Can you solve this KCSE Mathematics problem? Share your approach.",
        "What Biology topic do students find hardest in KCSE Paper 1?",
        "Quick quiz: which of these Science facts is false? Discuss.",
        "KCSE revision challenge: what are the key Chemistry formulae to memorise?",
        "Which English writing skill matters most in national exams?",
    ],
}

_DEFAULT_TOPICS: List[str] = [
    "What educational topic do you most want discussed on ElimuTalks?",
    "Best study habits for Kenyan students — share what works for you.",
    "How should we improve online learning resources for CBC students?",
    "Which subject do Kenyan students find hardest at secondary level?",
    "Share a tip that helped you or your learner succeed in exams.",
]


def _is_duplicate(topic: str, recent_topics: List[str], threshold: int = 5) -> bool:
    """
    Simple duplicate check: if any recent topic shares >= threshold words
    with the candidate, consider it a duplicate.
    """
    candidate_words = set(topic.lower().split())
    for rt in recent_topics:
        shared = candidate_words & set(rt.lower().split())
        # Ignore very common stop words
        _STOP = {"a", "an", "the", "and", "or", "to", "in", "of", "for",
                 "is", "it", "do", "you", "i", "my", "me", "your", "we",
                 "how", "what", "why", "when", "which", "who", "this", "that",
                 "with", "have", "are", "be", "can", "at", "by"}
        shared -= _STOP
        if len(shared) >= threshold:
            return True
    return False


def _select_topic(persona_name: str, recent_topics: List[str]) -> Optional[str]:
    """
    Pick a non-duplicate educational topic for the persona.
    Rotates through the pool, skipping topics that are too similar to recent ones.
    Returns None if every candidate is a duplicate.
    """
    pool = _PERSONA_TOPIC_POOLS.get(persona_name, _DEFAULT_TOPICS)
    # Rotate starting offset by hour-of-day so consecutive runs don't pick same topic
    hour = datetime.now(tz=timezone.utc).hour
    start = hour % len(pool)
    ordered = pool[start:] + pool[:start]
    for topic in ordered:
        if not _is_duplicate(topic, recent_topics):
            return topic
    return None


def _create_discussion_as_persona(
    persona_name: str,
    persona_display: str,
    topic: str,
) -> str:
    """
    Generate and post a discussion in the persona's voice.
    Uses the existing create_discussion() → generate_forum_post() → HTTP path.
    The persona voice is injected through a persona-aware prompt prefix.
    """
    from elimu_ai.tools.forum import generate_forum_post, save_forum_post, _pick_category
    from elimu_ai.gemini import generate as gemini_generate

    _PERSONA_VOICE_PREFIX: Dict[str, str] = {
        "teacher":    "As an experienced Kenyan teacher, write a genuine forum post.",
        "student":    "As a Kenyan secondary school student preparing for exams, write a genuine forum post.",
        "community":  "As a community member passionate about Kenyan education, write a forum post.",
        "counsellor": "As a career counsellor advising Kenyan students, write a forum post.",
        "parent":     "As a parent navigating CBC education in Kenya, write a forum post.",
        "librarian":  "As an educational librarian familiar with Elimu Library, write a forum post.",
        "quizmaster": "As a quiz and exam preparation specialist, write a forum post.",
    }

    voice = _PERSONA_VOICE_PREFIX.get(persona_name, "Write a genuine educational forum post.")
    prompt = (
        f"{voice}\n\n"
        f"Topic: {topic}\n\n"
        "Rules:\n"
        "- Plain text only, no Markdown.\n"
        "- Sound like a real community member, not a robot.\n"
        "- Return valid JSON with exactly two keys: "
        '"title" (string, max 80 chars) and "body" (string, 2-4 sentences).\n'
        "- The body should invite others to share their thoughts.\n"
        "- No markdown. No extra text outside the JSON object."
    )

    import json, re
    raw = gemini_generate(prompt)
    match = re.search(r"\{[\s\S]*?\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            title = data.get("title", f"Discussion: {topic[:60]}")
            body  = data.get("body",  topic)
        except Exception:
            title = f"Discussion: {topic[:60]}"
            body  = raw.strip() or topic
    else:
        title = f"Discussion: {topic[:60]}"
        body  = raw.strip() or topic

    cat = _pick_category(topic)
    import uuid
    ikey = f"proactive-{persona_name}-{uuid.uuid5(uuid.NAMESPACE_URL, title).hex}"
    thread = save_forum_post(title, body, cat, idempotency_key=ikey)
    if thread:
        slug = thread.get("slug", re.sub(r"[^\w-]", "-", title.lower())[:60])
        return f"created: /thread/{slug}/"
    # API unavailable — graceful degradation (still logged as success attempt)
    return f"generated (API unavailable): {title}"


def task_recommend_resources() -> str:
    """Post catalog recommendations to resource-request threads — via HTTP."""
    try:
        from elimu_ai.tools.forum import get_unanswered_threads, post_ai_answer
        from elimu_ai.tools.library import find_materials

        _KEYWORDS = ["notes", "revision", "past paper", "scheme", "resources",
                     "lesson plan", "assessment", "homework"]
        threads = get_unanswered_threads()
        if not threads:
            return "No unanswered threads — Django may be unavailable."

        count = 0
        for thread in threads:
            thread_id  = thread.get("id")
            title      = thread.get("title", "")
            post_count = thread.get("post_count", thread.get("posts_count", 0))
            if not thread_id or not title or post_count != 1:
                continue
            if any(kw in title.lower() for kw in _KEYWORDS):
                content = find_materials(title)
                if content and post_ai_answer(
                    thread_id=thread_id,
                    content=content,
                    idempotency_key=f"ai-recommend-{thread_id}",
                ):
                    count += 1
        return f"Posted {count} resource replies."
    except Exception as exc:
        logger.error("task_recommend_resources: %s", exc)
        return f"Error: {exc}"


def task_moderate_content() -> str:
    """
    Scan recent posts for spam/policy violations.

    Moderation uses the Django moderation API as the primary decision
    and the local deterministic rules as a second safety layer.

    The worker never writes directly to Django.
    """
    try:
        from elimu_ai.http_client import get_client
        from elimu_ai.tools.moderation import moderate

        client = get_client()

        # Fetch posts created within the last hour.
        try:
            data = client.get(
                "/api/ai/forum/recent-posts/",
                {"hours": "1"},
            )
            posts = data.get("results") or data.get("posts") or []
        except Exception as exc:
            logger.warning(
                "moderate_content: unable to fetch recent posts: %s",
                exc,
            )
            return "Django unavailable — moderation skipped."

        flagged = 0
        django_flagged = 0
        local_flagged = 0

        for post in posts:
            post_id = post.get("id")
            content = str(post.get("content", "")).strip()

            if not content:
                continue

            post_flagged = False

            # ── Layer 1: Django moderation API ───────────────────────────
            try:
                result = client.check_moderation(content)

                approved = result.get("approved", True)
                action = str(result.get("action", "allow")).lower()
                score = result.get("score", 0)
                reason = result.get("reason", "")

                if not approved or action not in ("allow", ""):
                    post_flagged = True
                    django_flagged += 1

                    logger.warning(
                        "moderation: Django flagged post #%s "
                        "(action=%s score=%s reason=%s)",
                        post_id,
                        action,
                        score,
                        reason,
                    )

            except Exception as exc:
                logger.warning(
                    "moderation: Django check failed for post #%s: %s",
                    post_id,
                    exc,
                )

            # ── Layer 2: local deterministic safety rules ───────────────
            local_result = moderate(content)

            if local_result != "Content approved.":
                post_flagged = True
                local_flagged += 1

                logger.warning(
                    "moderation: local rules flagged post #%s: %s",
                    post_id,
                    local_result,
                )

            if post_flagged:
                flagged += 1

        return (
            f"Scanned {len(posts)} posts, "
            f"flagged {flagged} "
            f"(Django: {django_flagged}, local: {local_flagged})."
        )

    except Exception as exc:
        logger.error("task_moderate_content: %s", exc)
        return f"Error: {exc}"


def task_catalog_sync() -> str:
    """Reload the local catalog cache from disk."""
    try:
        import elimu_ai.catalog_search as cs
        cs._index = None
        cs._catalog = None
        cs._load()
        return "Catalog cache refreshed."
    except Exception as exc:
        logger.error("task_catalog_sync: %s", exc)
        return f"Error: {exc}"


def task_health_check() -> str:
    try:
        from elimu_ai.health import get_health
        from elimu_ai.db.repositories import AgentLogRepository
        report = get_health()
        status = report.get("status", "unknown")
        AgentLogRepository().log_health_report(status, report)
        if report.get("gemini", {}).get("status") != "ok":
            from elimu_ai.email_alerts import alert_gemini_unavailable
            alert_gemini_unavailable()
        if report.get("postgresql", {}).get("status") != "ok":
            from elimu_ai.email_alerts import alert_db_disconnected
            alert_db_disconnected()
        return f"Health: {status}"
    except Exception as exc:
        logger.error("task_health_check: %s", exc)
        return f"Error: {exc}"


def task_summarise_memory() -> str:
    try:
        from elimu_ai.memory import memory_store
        sessions = memory_store.session_ids()
        summarised = sum(
            1 for sid in sessions
            if memory_store.should_summarise(sid)
            and memory_store.save_summary(sid, user_id=None)
        )
        return f"Summarised {summarised}/{len(sessions)} sessions."
    except Exception as exc:
        logger.error("task_summarise_memory: %s", exc)
        return f"Error: {exc}"


def task_generate_quiz_of_day() -> str:
    try:
        from elimu_ai.gemini import generate
        subjects = ["Mathematics", "Biology", "Chemistry", "Physics", "History", "Kiswahili"]
        subject  = subjects[datetime.now(tz=timezone.utc).timetuple().tm_yday % len(subjects)]
        prompt   = (
            f"Generate a short Quiz of the Day for Kenyan {subject} students. "
            "3 multiple choice questions with answers. Plain text only."
        )
        result = generate(prompt)
        if not result.startswith("Elimu AI"):
            return f"Quiz of Day ({subject}): generated."
        return "Quiz of Day: Gemini unavailable."
    except Exception as exc:
        logger.error("task_generate_quiz_of_day: %s", exc)
        return f"Error: {exc}"


def task_generate_study_tip() -> str:
    try:
        from elimu_ai.gemini import generate
        result = generate(
            "Write one practical study tip for a Kenyan secondary school student. "
            "Plain text, 2–3 sentences, friendly tone."
        )
        return "Study tip generated." if not result.startswith("Elimu AI") else "Gemini unavailable."
    except Exception as exc:
        logger.error("task_generate_study_tip: %s", exc)
        return f"Error: {exc}"


def task_scheduler_self_heal() -> str:
    """Verify scheduler is still running — no-op if healthy."""
    st = get_status()
    if not st.get("running"):
        logger.warning("scheduler: self-heal detected stopped state — restarting")
        start_scheduler(daemon=True)
        return "Scheduler restarted."
    return "Scheduler healthy."


def task_generate_article() -> str:
    """
    Generate one educational article autonomously.

    Decision flow:
      1. Check daily article limit (MAX_ARTICLES_PER_DAY)
      2. Find a non-duplicate topic from article pool
      3. Retrieve supporting Elimu Library resources
      4. Generate article with Gemini
      5. Moderate before logging

    Articles are idempotent — logged to ai_scheduler_log with job_name='generate_article'.
    """
    try:
        from elimu_ai.tools.article import generate_educational_article
        result = generate_educational_article()
        logger.info("task_generate_article: %s", result[:120])
        return result
    except Exception as exc:
        logger.error("task_generate_article: %s", exc)
        return f"Error: {exc}"


def task_continue_discussions() -> str:
    """
    Autonomously continue existing forum discussions toward the 30-post target.

    Finds threads that are active but below THREAD_GROWTH_TARGET and posts
    a meaningful persona-voiced contribution.

    This runs independently of task_generate_discussions so that growth
    activity and new-discussion creation don't compete for the same time slot.
    """
    try:
        result = _try_continue_existing_thread()
        if result:
            logger.info("task_continue_discussions: %s", result[:120])
            return result
        return "continue_discussions: no threads requiring continuation"
    except Exception as exc:
        logger.error("task_continue_discussions: %s", exc)
        return f"Error: {exc}"


def task_retry_failed_queries() -> str:
    """
    Retry previously unanswered/failed library queries.

    Strategy per attempt number:
      retry_count == 0 : normal retrieval (same as original request)
      retry_count == 1 : relaxed — drop metadata filters, semantic-only
      retry_count >= 2 : broadest — keyword only via catalog flat-file

    A question is marked resolved=TRUE only when actual evidence is found
    AND the answer passes VerifierAgent.  Category/browse fallbacks do NOT
    count as a resolution.

    Never generates a hallucinated answer.  Never marks resolved on empty.
    Non-fatal — any single failure is skipped and logged.
    """
    try:
        from elimu_ai.db.repositories import AgentLogRepository
        from elimu_ai.agents.verifier import VerifierAgent
        from elimu_ai.tools.library import _qdrant_search_for_query, _catalog_search_for_query
        from elimu_ai.catalog_search import _extract_from_keyword, search_catalog, format_recommendations

        repo     = AgentLogRepository()
        verifier = VerifierAgent()
        failures = repo.get_unresolved_failures_safe(
            max_retries=MAX_RETRY_ATTEMPTS, limit=20
        )
        if not failures:
            return "retry_failed_queries: nothing to retry."

        resolved_count  = 0
        attempted_count = 0

        for row in failures:
            fid      = row["id"]
            question = row["question"]
            retries  = row["retry_count"]

            try:
                attempted_count += 1

                # Extract structure from the question text
                grade, subject, term, year = _extract_from_keyword(question)

                if retries == 0:
                    # Attempt 1: normal retrieval with metadata filters
                    hits = _qdrant_search_for_query(grade, subject, term, year,
                                                    None, None, question)
                elif retries == 1:
                    # Attempt 2: relaxed — no metadata filters, semantic only
                    from elimu_ai.qdrant_db import search as qdrant_search
                    raw_hits = qdrant_search(question, score_threshold=0.0)
                    hits = []
                    for h in raw_hits:
                        p = h.payload or {}
                        url = p.get("url") or p.get("referral_url") or ""
                        if url:
                            hits.append({
                                "source":   "qdrant",
                                "score":    h.score,
                                "title":    p.get("title", ""),
                                "url":      url,
                                "grade":    p.get("grade", ""),
                                "subject":  p.get("subject", ""),
                                "term":     p.get("term", ""),
                                "year":     p.get("year", ""),
                                "doctype":  p.get("doctype", ""),
                                "audience": p.get("audience", ""),
                                "price":    p.get("price"),
                                "description": p.get("description", ""),
                                "curriculum":  p.get("curriculum", ""),
                            })
                else:
                    # Attempt 3: catalog flat-file keyword search only
                    docs = search_catalog(keyword=question, max_results=5)
                    hits = [
                        {
                            "source": "catalog", "score": 0.0,
                            "title": d.get("title", ""), "url": d.get("url", ""),
                            "grade": d.get("grade", ""), "subject": d.get("subject", ""),
                            "term":  d.get("term", ""),  "year":    d.get("year", ""),
                            "doctype": d.get("doctype", ""), "audience": d.get("audience", ""),
                            "price": d.get("price"), "description": d.get("description", ""),
                            "curriculum": d.get("curriculum", ""),
                        }
                        for d in docs if d.get("url")
                    ]

                if not hits:
                    # No evidence found — increment retry count, leave unresolved
                    repo.increment_retry(fid)
                    logger.info("retry_failed_queries: no hits for %r (attempt %d)",
                                question[:60], retries + 1)
                    continue

                # Format the evidence and verify
                from elimu_ai.tools.library import _format_evidence
                answer = _format_evidence(hits[:5], question)
                result = verifier.verify(answer, question, [])

                if result.passed:
                    repo.mark_resolved(fid)
                    resolved_count += 1
                    logger.info(
                        "retry_failed_queries: resolved %r after %d attempt(s)",
                        question[:60], retries + 1,
                    )
                    # Cache the result so live requests can find it immediately
                    _cache_resolved_answer(question, answer)
                else:
                    repo.increment_retry(fid)
                    logger.info(
                        "retry_failed_queries: evidence found but verification failed "
                        "for %r — issues=%s",
                        question[:60], result.issues,
                    )

            except Exception as row_exc:
                logger.warning("retry_failed_queries: error on row %d: %s", fid, row_exc)
                try:
                    repo.increment_retry(fid)
                except Exception:
                    pass

        return (
            f"retry_failed_queries: attempted={attempted_count} "
            f"resolved={resolved_count} remaining={attempted_count - resolved_count}"
        )

    except Exception as exc:
        logger.error("task_retry_failed_queries: %s", exc)
        return f"Error: {exc}"


def _cache_resolved_answer(question: str, answer: str) -> None:
    """Store a verified retry result in ai_recommendation_cache. Non-fatal."""
    try:
        import hashlib
        from elimu_ai.db.repositories import RecommendationRepository
        cache_key = "retry:" + hashlib.sha256(question.lower().strip().encode()).hexdigest()[:32]
        RecommendationRepository().set_cached(
            cache_key=cache_key,
            result_json=answer,
            ttl_hours=48,
        )
    except Exception as exc:
        logger.debug("_cache_resolved_answer: %s", exc)


# ── Task registry ─────────────────────────────────────────────────────────────

_TASK_REGISTRY: List[Tuple[str, Callable[[], str], int]] = [
    ("answer_unanswered",    task_answer_unanswered,    SCHEDULER_ANSWER_INTERVAL),
    ("generate_discussions", task_generate_discussions,  SCHEDULER_DISCUSS_INTERVAL),
    ("continue_discussions", task_continue_discussions,  THREAD_CONTINUATION_COOLDOWN),
    ("generate_article",     task_generate_article,      SCHEDULER_ARTICLE_INTERVAL),
    ("recommend_resources",  task_recommend_resources,   SCHEDULER_RECOMMEND_INTERVAL),
    ("moderate_content",     task_moderate_content,      SCHEDULER_MODERATE_INTERVAL),
    ("catalog_sync",         task_catalog_sync,          SCHEDULER_CATALOG_INTERVAL),
    ("health_check",         task_health_check,          900),
    ("summarise_memory",     task_summarise_memory,      3600),
    ("quiz_of_day",          task_generate_quiz_of_day,  86400),
    ("study_tip",            task_generate_study_tip,    43200),
    ("scheduler_self_heal",  task_scheduler_self_heal,   300),
    ("retry_failed_queries", task_retry_failed_queries,  SCHEDULER_RETRY_FAILURES_INTERVAL),
]


def _make_job(name: str, fn: Callable[[], str]) -> Callable[[], None]:
    def job() -> None:
        t0 = time.monotonic()
        try:
            result = fn()
        except Exception as exc:
            result = f"Error: {exc}"
            logger.error("scheduler [%s] raised: %s", name, exc)
        duration_ms = int((time.monotonic() - t0) * 1000)
        now      = datetime.now(tz=timezone.utc).isoformat()
        is_error = result.startswith("Error:")
        scheduler_status["last_run"][name] = {"at": now, "result": result}
        if is_error:
            scheduler_status["errors"][name] = {"at": now, "detail": result}
        else:
            scheduler_status["errors"].pop(name, None)
        (logger.error if is_error else logger.info)(
            "scheduler [%s]: %s (ms=%d)", name, result, duration_ms
        )
        try:
            from elimu_ai.db.repositories import SchedulerRepository
            SchedulerRepository().log_job(
                job_name=name,
                status="error" if is_error else "ok",
                result=result,
                duration_ms=duration_ms,
                error=result if is_error else None,
            )
        except Exception as db_exc:
            logger.debug("scheduler: DB log failed (non-fatal): %s", db_exc)
    job.__name__ = f"task_{name}"
    return job


def _build_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.executors.pool import ThreadPoolExecutor
    from apscheduler.jobstores.memory import MemoryJobStore
    sched = BackgroundScheduler(
        jobstores={"default": MemoryJobStore()},
        executors={"default": ThreadPoolExecutor(max_workers=6)},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
        timezone="Africa/Nairobi",
    )
    for name, fn, interval in _TASK_REGISTRY:
        sched.add_job(
            func=_make_job(name, fn),
            trigger="interval",
            seconds=interval,
            id=name,
            name=f"ElimuAI:{name}",
            replace_existing=True,
        )
    return sched


def start_scheduler(daemon: bool = True) -> Any:
    """Start APScheduler. Safe to call multiple times — reuses running instance."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.running:
            logger.debug("scheduler: already running — reusing.")
            return _scheduler_instance
        sched = _build_scheduler()
        sched.start(paused=False)
        _scheduler_instance = sched
    scheduler_status["running"]    = True
    scheduler_status["started_at"] = datetime.now(tz=timezone.utc).isoformat()
    logger.info("APScheduler started (%d jobs)", len(_TASK_REGISTRY))
    return sched


def shutdown_scheduler(wait: bool = True) -> None:
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance and _scheduler_instance.running:
            _scheduler_instance.shutdown(wait=wait)
        scheduler_status["running"] = False
        _scheduler_instance = None
    logger.info("APScheduler shut down (wait=%s).", wait)


def run_all_tasks() -> Dict[str, str]:
    results: Dict[str, str] = {}
    for name, fn, _ in _TASK_REGISTRY:
        try:
            results[name] = fn()
        except Exception as exc:
            results[name] = f"Error: {exc}"
    return results


def get_status() -> Dict[str, Any]:
    return dict(scheduler_status)


def _run_standalone() -> None:
    """Entry point for: python -m elimu_ai.scheduler"""
    from elimu_ai.logging_config import configure_logging
    configure_logging()
    logger.info("Elimu AI Scheduler — standalone mode")
    start_scheduler(daemon=False)
    stop_event = threading.Event()

    def _sig(signum, frame):
        logger.info("Signal %d received — shutting down.", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    stop_event.wait()
    shutdown_scheduler(wait=True)
    logger.info("Scheduler exited.")


if __name__ == "__main__":
    _run_standalone()
