"""
elimu_ai/diagnostics/community_flow.py

Safe community flow diagnostic — NO AI generation, NO posting.

Run:
    python -m elimu_ai.diagnostics.community_flow

Shows exactly what the community scheduler would do without doing it.
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def run() -> None:
    print()
    print("=" * 60)
    print("COMMUNITY FLOW DIAGNOSTIC")
    print("No AI generation. No posts created.")
    print("=" * 60)

    # ── 1. Unanswered threads ──────────────────────────────────────────────
    print()
    print("UNANSWERED THREADS (post_count == 1, cutoff 6h):")
    try:
        from elimu_ai.tools.forum import get_unanswered_threads
        from elimu_ai.community_tasks import _get_post_count, select_thread_by_priority

        unanswered = get_unanswered_threads(cutoff_hours=6)
        eligible_unanswered = [t for t in unanswered if _get_post_count(t) == 1]
        print(f"  API returned: {len(unanswered)} threads")
        print(f"  Eligible (post_count==1): {len(eligible_unanswered)}")
        for t in eligible_unanswered[:5]:
            print(f"    thread={t.get('id')} posts={_get_post_count(t)} {t.get('title','')[:55]!r}")
        if not eligible_unanswered:
            print("  (none)")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    # ── 2. Active threads by priority ─────────────────────────────────────
    print()
    print("ACTIVE THREADS — sorted by post count (fewest first):")
    try:
        from elimu_ai.tools.forum import get_active_threads_for_growth
        from elimu_ai.community_tasks import _get_post_count, select_thread_by_priority
        from elimu_ai.config import THREAD_MIN_POSTS_FOR_CONTINUATION, THREAD_GROWTH_TARGET

        active = get_active_threads_for_growth(
            min_posts=THREAD_MIN_POSTS_FOR_CONTINUATION,
            max_posts=THREAD_GROWTH_TARGET - 1,
            limit=20,
        )
        active_sorted = sorted(active, key=lambda t: _get_post_count(t))
        print(f"  count={len(active_sorted)}")
        for t in active_sorted[:8]:
            print(
                f"    thread={t.get('id'):5} posts={_get_post_count(t):3} "
                f"title={t.get('title','')[:50]!r}"
            )
        if not active_sorted:
            print("  (none)")
        if active_sorted:
            priority = select_thread_by_priority(active_sorted)
            print(f"  SELECTED BY PRIORITY: thread={priority.get('id')} posts={_get_post_count(priority)} {priority.get('title','')[:50]!r}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    # ── 3. Role last activity ──────────────────────────────────────────────
    print()
    print("MAIN ROLE LAST ACTIVITY (parent/teacher/student):")
    try:
        from elimu_ai.db.repositories import ProactiveDiscussionRepository
        from elimu_ai.community_tasks import get_role_last_activity, select_role_lru, MAIN_ROLES

        repo = ProactiveDiscussionRepository()
        for role in MAIN_ROLES:
            secs = get_role_last_activity(repo, role)
            if secs is None:
                label = "never"
            elif secs == float("inf"):
                label = "never (some personas unused)"
            else:
                label = f"{secs:.0f}s ago ({secs/3600:.1f}h)"
            print(f"  {role:10} {label}")

        selected_role = select_role_lru(repo)
        print(f"  SELECTED ROLE: {selected_role}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    # ── 4. Candidate personas ──────────────────────────────────────────────
    print()
    print("CANDIDATE PERSONAS (for selected role):")
    try:
        from elimu_ai.db.repositories import ProactiveDiscussionRepository
        from elimu_ai.community_tasks import select_role_lru, select_persona_for_role
        from elimu_ai.personas.named import get_personas_by_category
        from elimu_ai.config import PERSONA_COOLDOWN

        repo = ProactiveDiscussionRepository()
        role = select_role_lru(repo)
        personas = get_personas_by_category(role)
        for p in personas:
            secs = repo.seconds_since_persona_last_posted_safe(p.key)
            on_cooldown = (secs is not None and secs < PERSONA_COOLDOWN)
            label = "never" if secs is None else f"{secs:.0f}s ago"
            cooldown_label = " [ON COOLDOWN]" if on_cooldown else ""
            print(f"  {p.key:15} {p.display_name:20} {label}{cooldown_label}")

        selected = select_persona_for_role(repo, role, PERSONA_COOLDOWN)
        if selected:
            print(f"  SELECTED PERSONA: {selected[0]} ({selected[1]})")
        else:
            print("  SELECTED PERSONA: none eligible")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    # ── 5. Decision summary ────────────────────────────────────────────────
    print()
    print("DECISION SUMMARY:")
    try:
        from elimu_ai.tools.forum import get_unanswered_threads, get_active_threads_for_growth
        from elimu_ai.community_tasks import (
            _get_post_count, select_thread_by_priority,
            select_role_lru, select_persona_for_role, MAIN_ROLES
        )
        from elimu_ai.db.repositories import ProactiveDiscussionRepository
        from elimu_ai.config import (
            PERSONA_COOLDOWN,
            THREAD_MIN_POSTS_FOR_CONTINUATION,
            THREAD_GROWTH_TARGET,
        )

        repo = ProactiveDiscussionRepository()

        unanswered = get_unanswered_threads(cutoff_hours=6)
        eligible_unanswered = [t for t in unanswered if _get_post_count(t) == 1]

        if eligible_unanswered:
            thread = select_thread_by_priority(eligible_unanswered)
            decision = "ANSWER_UNANSWERED"
        else:
            active = get_active_threads_for_growth(
                min_posts=THREAD_MIN_POSTS_FOR_CONTINUATION,
                max_posts=THREAD_GROWTH_TARGET - 1,
                limit=20,
            )
            thread = select_thread_by_priority(active)
            decision = "PARTICIPATE" if thread else "NO_THREAD"

        role = select_role_lru(repo)
        persona = select_persona_for_role(repo, role, PERSONA_COOLDOWN)

        print(f"  Decision:   {decision}")
        if thread:
            print(f"  Thread:     id={thread.get('id')} posts={_get_post_count(thread)} {thread.get('title','')[:50]!r}")
        else:
            print("  Thread:     (none found)")
        print(f"  Role:       {role}")
        if persona:
            print(f"  Persona:    {persona[0]} ({persona[1]})")
        else:
            print("  Persona:    (none eligible)")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    print()
    print("NO AI GENERATION PERFORMED")
    print("NO POSTS CREATED")
    print("=" * 60)


if __name__ == "__main__":
    run()
