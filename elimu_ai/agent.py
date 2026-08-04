"""
elimu_ai/agent.py

Autonomous orchestration engine — the brain of Elimu AI.

Pipeline per request:
  1. Route → decide_persona()
  2. Extract structured context hints from question + history
  3. Search Qdrant for semantic context
  4. Run catalog search when relevant (librarian persona, or resource requests)
  5. Build persona-specific prompt
  6. Generate response via Gemini
  7. Optionally generate a quiz section (multi-tool)
  8. Clean output and rewrite links with referral params
  9. Return structured result dict

Multi-tool example:
  "I need Grade 8 Mathematics revision and a quiz."
  → qdrant_search + catalog_search + teacher_prompt + quiz_prompt
  → single response with explanation + quiz + catalog links
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from elimu_ai.router import decide_persona
from elimu_ai.qdrant_db import search as qdrant_search
from elimu_ai.gemini import generate
from elimu_ai.helpers import clean_answer, rewrite_links, referral_url
from elimu_ai.catalog_search import (
    catalog_available,
    format_recommendations,
    search_catalog,
)
from elimu_ai.tools.teacher import (
    build_teacher_prompt,
    extract_context_hints,
    extract_context_from_history,
)
from elimu_ai.tools.quiz import build_quiz_prompt, quiz_fallback
from elimu_ai.tools.community import build_community_prompt
from elimu_ai.tools.library import find_materials, build_librarian_prompt

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _qdrant_context(hits: List) -> str:
    """Convert Qdrant ScoredPoint list into a readable plain-text context block."""
    if not hits:
        return ""
    parts = []
    for hit in hits:
        p = hit.payload or {}
        title = p.get("title", "")
        desc  = p.get("description", "")
        url   = p.get("url", "")
        parts.append(f"Title: {title}\nDescription: {desc}\nURL: {url}")
    return "\n\n".join(parts)


def _catalog_context(question: str, ctx_hints: Dict) -> str:
    """Run a catalog search and return formatted results as a string."""
    if not catalog_available():
        return ""
    try:
        results = search_catalog(
            grade=ctx_hints.get("grade"),
            subject=ctx_hints.get("subject"),
            term=ctx_hints.get("term"),
            year=ctx_hints.get("year"),
            audience=ctx_hints.get("audience"),
            keyword=question,
            max_results=5,
        )
        return format_recommendations(results, question) if results else ""
    except Exception as exc:
        logger.warning("agent: catalog context failed: %s", exc)
        return ""


def _source_urls(hits: List) -> List[str]:
    """Extract and tag source URLs from Qdrant hits."""
    sources = []
    for hit in hits:
        try:
            url = (hit.payload or {}).get("url", "")
            if url:
                sources.append(referral_url(url))
        except Exception:
            pass
    return sources


def _wants_quiz(question: str) -> bool:
    """True when the question asks for a quiz alongside other content."""
    lower = question.lower()
    return any(kw in lower for kw in [
        "and a quiz", "quiz me", "test me", "give me a quiz",
        "and quiz", "also quiz", "with a quiz",
    ])


def _wants_resources(question: str, ctx_hints: Dict) -> bool:
    """True when appending catalog resources would add value."""
    lower = question.lower()
    if any(kw in lower for kw in [
        "and notes", "and resources", "and materials",
        "revision materials", "find me", "get me",
    ]):
        return True
    # Always append if we know the grade or subject
    return bool(ctx_hints.get("grade") or ctx_hints.get("subject"))


def _build_prompt(
    persona: str,
    question: str,
    qdrant_ctx: str,
    history: Optional[List[Dict]],
) -> str:
    """Select and render the correct prompt for the given persona."""
    if persona == "teacher":
        return build_teacher_prompt(question, qdrant_ctx, history)
    if persona == "quiz":
        return build_quiz_prompt(question, qdrant_ctx)
    if persona == "community":
        return build_community_prompt(question, qdrant_ctx)
    if persona == "librarian":
        return build_librarian_prompt(question, qdrant_ctx)
    return build_teacher_prompt(question, qdrant_ctx, history)


# ── Public entry point ────────────────────────────────────────────────────────

def run_agent(
    question: str,
    history: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Execute the autonomous agent pipeline for a single user request.

    Parameters
    ----------
    question : str
        The user's message.
    history : list of {role: str, content: str}, optional
        Prior conversation turns for context.

    Returns
    -------
    dict:
        persona  : str         — persona that handled the request
        answer   : str         — clean plain-text response
        sources  : list[str]   — referral-tagged source URLs
        tools    : list[str]   — tools invoked during this request
    """
    if not question or not question.strip():
        return {
            "persona": "teacher",
            "answer": "Please ask a question and I'll be happy to help!",
            "sources": [],
            "tools": [],
        }

    history = history or []
    tools_used: List[str] = []

    logger.info("agent: question=%r", question[:100])

    # ── 1. Persona routing ────────────────────────────────────────────────────
    persona = decide_persona(question)
    logger.info("agent: persona=%s", persona)

    # ── 2. Context extraction ─────────────────────────────────────────────────
    ctx_hints = extract_context_hints(question)
    if history:
        hist_hints = extract_context_from_history(history[-6:])
        for key in ("grade", "subject", "term", "year", "audience"):
            if not ctx_hints.get(key) and hist_hints.get(key):
                ctx_hints[key] = hist_hints[key]

    logger.debug("agent: ctx_hints=%s", ctx_hints)

    # ── 3. Qdrant semantic search ─────────────────────────────────────────────
    tools_used.append("qdrant_search")
    hits = qdrant_search(question)
    qdrant_ctx = _qdrant_context(hits)

    # ── 4a. Librarian — return catalog results directly (no Gemini needed) ───
    if persona == "librarian":
        tools_used.append("catalog_search")
        catalog_answer = find_materials(
            question=question,
            grade=ctx_hints.get("grade"),
            subject=ctx_hints.get("subject"),
            term=ctx_hints.get("term"),
            year=ctx_hints.get("year"),
            audience=ctx_hints.get("audience"),
            history=history,
        )
        logger.info("agent: librarian done, sources=%d", len(_source_urls(hits)))
        return {
            "persona": persona,
            "answer": catalog_answer,
            "sources": _source_urls(hits),
            "tools": tools_used,
        }

    # ── 4b. Optional catalog section for other personas ───────────────────────
    catalog_section = ""
    if _wants_resources(question, ctx_hints):
        tools_used.append("catalog_search")
        catalog_section = _catalog_context(question, ctx_hints)

    # ── 5. Build persona prompt ───────────────────────────────────────────────
    prompt = _build_prompt(persona, question, qdrant_ctx, history)

    # ── 6. Gemini generation ──────────────────────────────────────────────────
    tools_used.append("gemini_generate")
    raw_answer = generate(prompt)

    # Detect Gemini failure and use fallback for quiz persona
    gemini_failed = raw_answer.startswith("Elimu AI") or raw_answer.startswith("Gemini error")
    if gemini_failed and persona == "quiz":
        tools_used.append("quiz_fallback")
        answer = quiz_fallback(question)
        return {
            "persona": persona,
            "answer": answer,
            "sources": _source_urls(hits),
            "tools": tools_used,
        }

    # ── 7. Optional quiz section (multi-tool) ─────────────────────────────────
    quiz_section = ""
    if not gemini_failed and persona == "teacher" and _wants_quiz(question):
        tools_used.append("quiz_generate")
        quiz_prompt_str = build_quiz_prompt(question, qdrant_ctx)
        quiz_raw = generate(quiz_prompt_str)
        if not quiz_raw.startswith("Elimu AI"):
            quiz_section = clean_answer(quiz_raw)

    # ── 8. Clean and assemble output ──────────────────────────────────────────
    answer = clean_answer(raw_answer)
    answer = rewrite_links(answer)

    if quiz_section:
        answer += "\n\nPractice Quiz\n\n" + quiz_section

    if catalog_section and not gemini_failed:
        answer += "\n\nRecommended Materials\n\n" + catalog_section

    # ── 9. Sources ────────────────────────────────────────────────────────────
    sources = _source_urls(hits)

    logger.info(
        "agent: done persona=%s tools=%s answer_len=%d sources=%d",
        persona, tools_used, len(answer), len(sources),
    )

    return {
        "persona": persona,
        "answer": answer,
        "sources": sources,
        "tools": tools_used,
    }
