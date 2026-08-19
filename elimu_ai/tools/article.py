"""
elimu_ai/tools/article.py

Autonomous article generation tool.

Generates educational articles for ElimuTalks based on:
  - Popular forum topics
  - Recurring unanswered questions
  - High-value educational topics
  - Seasonal examination needs
  - Gaps in existing content

Rules:
  - Never generates articles randomly at high frequency.
  - Always checks for duplicate topics before generating.
  - All content passes moderation before being published.
  - URLs come from Elimu Library evidence only — never invented.
  - Article generation is rate-limited via config (MAX_ARTICLES_PER_DAY).
  - Uses existing Qdrant/catalog retrieval for supporting resources.
  - Uses existing ai_scheduler_log for activity tracking.
  - No new database tables required.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Article topic seeds ───────────────────────────────────────────────────────
# Organised by educational category. Rotated to avoid repetition.

_ARTICLE_TOPICS: List[Dict] = [
    # KCSE exam preparation
    {
        "title": "How to Prepare for KCSE Mathematics: A Practical Guide",
        "category": "exam_prep",
        "keywords": ["kcse", "mathematics", "revision"],
    },
    {
        "title": "KCSE Biology: Top 10 Topics Students Struggle With",
        "category": "exam_prep",
        "keywords": ["kcse", "biology", "revision"],
    },
    {
        "title": "Effective KCSE English Paper 1 Writing Strategies",
        "category": "exam_prep",
        "keywords": ["kcse", "english", "writing"],
    },
    {
        "title": "KCSE Chemistry: Understanding Organic Chemistry for Form 4",
        "category": "exam_prep",
        "keywords": ["kcse", "chemistry", "form4"],
    },
    {
        "title": "How to Score an A in KCSE History and Government",
        "category": "exam_prep",
        "keywords": ["kcse", "history", "revision"],
    },
    # CBC learning
    {
        "title": "Understanding CBC Assessment: A Guide for Parents",
        "category": "cbc",
        "keywords": ["cbc", "assessment", "parents"],
    },
    {
        "title": "CBC Grade 6 Transition: What Students Need to Know",
        "category": "cbc",
        "keywords": ["cbc", "grade6", "transition"],
    },
    {
        "title": "How CBC Competency-Based Learning Differs from 8-4-4",
        "category": "cbc",
        "keywords": ["cbc", "curriculum", "comparison"],
    },
    # Study skills
    {
        "title": "Five Study Techniques That Actually Work for Kenyan Students",
        "category": "study_skills",
        "keywords": ["study", "revision", "techniques"],
    },
    {
        "title": "How to Create an Effective Revision Timetable for KCSE",
        "category": "study_skills",
        "keywords": ["revision", "timetable", "kcse"],
    },
    {
        "title": "Using Past Papers to Improve Your KCSE Performance",
        "category": "study_skills",
        "keywords": ["past_papers", "revision", "kcse"],
    },
    # Teacher resources
    {
        "title": "How to Write a CBC Scheme of Work: Step-by-Step Guide",
        "category": "teacher_resources",
        "keywords": ["scheme_of_work", "cbc", "teachers"],
    },
    {
        "title": "Lesson Planning for CBC: A Practical Teacher's Guide",
        "category": "teacher_resources",
        "keywords": ["lesson_plan", "cbc", "teachers"],
    },
    # Career guidance
    {
        "title": "University vs TVET After KCSE: Making the Right Choice",
        "category": "career",
        "keywords": ["career", "university", "tvet"],
    },
    {
        "title": "Top Scholarships for Kenyan Students in 2024–2025",
        "category": "career",
        "keywords": ["scholarships", "kenya", "students"],
    },
]

_ARTICLE_PROMPT = """\
You are an expert Kenyan educator writing a high-quality SEO-optimised educational article for ElimuTalks.

Article title: {title}
Target audience: Kenyan students, teachers, and parents
Educational context: Kenyan CBC and 8-4-4 curriculum

Supporting resources from Elimu Library (include relevant ones naturally):
{resources}

Write a complete educational article following this structure:
1. Introduction (2-3 sentences — explain why this matters)
2. Main body (3-4 well-developed paragraphs)
3. Practical tips or examples (use numbered list if appropriate)
4. Connection to Elimu Library resources (mention 1-2 specific resources)
5. Conclusion (1-2 sentences — encourage action)

Rules:
- Plain text only. No Markdown headers (##), no asterisks (**), no code blocks.
- Write naturally and warmly — like an experienced Kenyan educator.
- Do not fabricate document URLs or titles. Use only the resources provided above.
- Minimum 300 words, maximum 600 words.
- Do not start with "Certainly" or "Sure".
- Do not repeat the title in the body.

Write the article body now:
"""


def _count_articles_today() -> int:
    """Count articles generated today using ai_scheduler_log."""
    try:
        from elimu_ai.db.repositories import SchedulerRepository
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM ai_scheduler_log"
                    " WHERE job_name='generate_article'"
                    " AND status='ok'"
                    " AND ran_at >= CURRENT_DATE",
                )
                row = cur.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _get_recent_article_titles(limit: int = 20) -> List[str]:
    """Return recent article titles to avoid duplicates."""
    try:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT result FROM ai_scheduler_log"
                    " WHERE job_name='generate_article'"
                    " ORDER BY ran_at DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
        titles = []
        for r in (rows or []):
            try:
                data = json.loads(r[0]) if r[0] else {}
                t = data.get("title", "")
                if t:
                    titles.append(t.lower())
            except Exception:
                pass
        return titles
    except Exception:
        return []


def _topic_is_duplicate(title: str, recent_titles: List[str]) -> bool:
    """Return True if the title is too similar to a recent article."""
    title_words = set(w.lower() for w in title.split() if len(w) > 3)
    _STOP = {"that", "this", "with", "have", "from", "your", "their",
             "they", "when", "will", "been", "more", "most", "some"}
    title_words -= _STOP
    for rt in recent_titles:
        rt_words = set(w.lower() for w in rt.split() if len(w) > 3) - _STOP
        if not rt_words:
            continue
        shared = title_words & rt_words
        score = len(shared) / max(len(title_words), len(rt_words))
        if score >= 0.5:
            return True
    return False


def _select_article_topic(recent_titles: List[str]) -> Optional[Dict]:
    """Pick a non-duplicate article topic. Rotate by day-of-year."""
    from datetime import datetime, timezone
    day = datetime.now(tz=timezone.utc).timetuple().tm_yday
    start = day % len(_ARTICLE_TOPICS)
    ordered = _ARTICLE_TOPICS[start:] + _ARTICLE_TOPICS[:start]
    for topic in ordered:
        if not _topic_is_duplicate(topic["title"], recent_titles):
            return topic
    return None


def _fetch_supporting_resources(keywords: List[str]) -> str:
    """Retrieve supporting Elimu Library resources for the article."""
    try:
        from elimu_ai.tools.library import find_materials
        query = " ".join(keywords[:3])
        result = find_materials(question=query)
        # Return only if actual documents were found (not just browse links)
        if "elimulibrary.com/site/document/" in result:
            return result[:600]
    except Exception as exc:
        logger.debug("article: resource fetch failed: %s", exc)
    return "No specific Elimu Library resources found for this topic."


def _generate_article_content(title: str, resources: str) -> Optional[str]:
    """Use Gemini to generate the article body."""
    try:
        from elimu_ai.gemini import generate
        prompt = _ARTICLE_PROMPT.format(title=title, resources=resources)
        raw = generate(prompt)
        if not raw or raw.startswith("Elimu AI") or raw.startswith("Gemini error"):
            return None
        return raw.strip()
    except Exception as exc:
        logger.error("article: Gemini generation failed: %s", exc)
        return None


def _log_article(title: str, status: str, word_count: int = 0) -> None:
    """Log article generation to ai_scheduler_log."""
    try:
        from elimu_ai.db.repositories import SchedulerRepository
        from datetime import datetime, timezone
        result_json = json.dumps({
            "title": title[:200],
            "status": status,
            "word_count": word_count,
        })
        SchedulerRepository().log_job(
            job_name="generate_article",
            status="ok" if status == "generated" else "skipped",
            result=result_json[:500],
            duration_ms=0,
        )
    except Exception as exc:
        logger.debug("article: log failed: %s", exc)


def generate_educational_article() -> str:
    """
    Generate one educational article autonomously.

    Decision flow:
      1. Check daily limit
      2. Find a non-duplicate topic
      3. Retrieve supporting Elimu Library resources
      4. Generate article content with Gemini
      5. Moderate the content
      6. Log result

    Returns a status string suitable for the scheduler result.
    """
    from elimu_ai.config import MAX_ARTICLES_PER_DAY

    # Guard: daily limit
    today_count = _count_articles_today()
    if today_count >= MAX_ARTICLES_PER_DAY:
        logger.info(
            "article: daily limit reached (%d/%d)", today_count, MAX_ARTICLES_PER_DAY
        )
        return f"skipped: daily limit {today_count}/{MAX_ARTICLES_PER_DAY}"

    # Select topic
    recent_titles = _get_recent_article_titles(limit=20)
    topic = _select_article_topic(recent_titles)
    if not topic:
        logger.info("article: no fresh topic available")
        _log_article("", "skipped_duplicate")
        return "skipped: no fresh topic available"

    title = topic["title"]
    logger.info("article: selected topic=%r", title)

    # Fetch supporting resources
    resources = _fetch_supporting_resources(topic.get("keywords", []))

    # Generate content
    content = _generate_article_content(title, resources)
    if not content:
        logger.warning("article: Gemini generation failed for %r", title)
        _log_article(title, "failed_generation")
        return f"Error: article generation failed for {title[:60]}"

    # Moderation
    from elimu_ai.tools.moderation import moderate
    mod_result = moderate(content)
    if mod_result != "Content approved.":
        logger.warning("article: moderation blocked article %r: %s", title, mod_result)
        _log_article(title, "blocked_moderation")
        return f"skipped: moderation blocked ({mod_result})"

    word_count = len(content.split())
    _log_article(title, "generated", word_count=word_count)

    logger.info(
        "article: generated successfully title=%r words=%d", title, word_count
    )
    return f"generated: {title[:60]} ({word_count} words)"
