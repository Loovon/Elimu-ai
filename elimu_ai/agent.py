"""
elimu_ai/agent.py

Orchestration engine — the autonomous agent.

Responsibilities:
  1. Decide persona via router.
  2. Search Qdrant for semantic context.
  3. Run catalog tool (library) when relevant.
  4. Build the appropriate prompt.
  5. Call Gemini for generation.
  6. Clean and rewrite the output.
  7. Collect and append source links.
  8. Return a structured response dict.

The agent may invoke multiple tools in one request.
Example: a student asking for both revision notes AND a quiz will trigger
the library tool AND the quiz prompt in the same pass.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from elimu_ai.router import decide_persona
from elimu_ai.qdrant_db import search as qdrant_search
from elimu_ai.gemini import generate
from elimu_ai.helpers import clean_answer, rewrite_links, referral_url
from elimu_ai.catalog_search import (
    search_catalog,
    format_recommendations,
    catalog_available,
)
from elimu_ai.tools.teacher import (
    build_teacher_prompt,
    extract_context_hints,
    extract_context_from_history,
)
from elimu_ai.tools.quiz import build_quiz_prompt
from elimu_ai.tools.community import build_community_prompt
from elimu_ai.tools.library import find_materials, build_librarian_prompt


# ── Context builders ──────────────────────────────────────────────────────────

def _qdrant_context(hits: List) -> str:
    """Convert Qdrant ScoredPoint objects into a plain-text context block."""
    if not hits:
        return ""
    parts = []
    for hit in hits:
        p = hit.payload or {}
        parts.append(
            f"Title: {p.get('title', '')}\n"
            f"Description: {p.get('description', '')}\n"
            f"URL: {p.get('url', '')}"
        )
    return "\n\n".join(parts)


def _catalog_context(question: str, ctx_hints: Dict) -> str:
    """Run catalog search and return formatted results as a string."""
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
    except Exception:
        return ""


def _source_urls(hits: List) -> List[str]:
    """Extract and rewrite source URLs from Qdrant hits."""
    sources = []
    for hit in hits:
        try:
            url = hit.payload.get("url", "")
            if url:
                sources.append(referral_url(url))
        except Exception:
            pass
    return sources


# ── Multi-tool detection ──────────────────────────────────────────────────────

def _wants_quiz(question: str) -> bool:
    """True if the question explicitly asks for a quiz alongside other content."""
    lower = question.lower()
    return any(kw in lower for kw in ["and a quiz", "quiz me", "test me", "give me a quiz"])


def _wants_resources(question: str) -> bool:
    """True if the question explicitly asks for materials / resources."""
    lower = question.lower()
    return any(
        kw in lower
        for kw in [
            "and notes", "and resources", "and materials",
            "revision materials", "find me", "get me",
        ]
    )


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(
    persona: str,
    question: str,
    qdrant_ctx: str,
    history: Optional[List[Dict]],
) -> str:
    """Select and build the correct prompt for the given persona."""
    if persona == "teacher":
        return build_teacher_prompt(question, qdrant_ctx, history)
    if persona == "quiz":
        return build_quiz_prompt(question, qdrant_ctx)
    if persona == "community":
        return build_community_prompt(question, qdrant_ctx)
    if persona == "librarian":
        return build_librarian_prompt(question, qdrant_ctx)
    # Fallback — default to teacher
    return build_teacher_prompt(question, qdrant_ctx, history)


# ── Public entry point ────────────────────────────────────────────────────────

def run_agent(
    question: str,
    history: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Execute the autonomous agent pipeline.

    Parameters
    ----------
    question : str
        The user's message.
    history : list of {role, content} dicts, optional
        Prior conversation turns for context.

    Returns
    -------
    dict with keys:
        persona  : str   — which persona handled the request
        answer   : str   — cleaned plain-text response
        sources  : list  — referral URLs from Qdrant hits
        tools    : list  — names of tools that were invoked
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

    # ── Step 1: Decide persona ────────────────────────────────────────────────
    persona = decide_persona(question)

    # ── Step 2: Extract structured context hints ──────────────────────────────
    ctx_hints = extract_context_hints(question)
    if history:
        hist_hints = extract_context_from_history(history[-6:])
        for key in ("grade", "subject", "term", "year", "audience"):
            if not ctx_hints.get(key) and hist_hints.get(key):
                ctx_hints[key] = hist_hints[key]

    # ── Step 3: Search Qdrant ─────────────────────────────────────────────────
    tools_used.append("qdrant_search")
    hits = qdrant_search(question)
    qdrant_ctx = _qdrant_context(hits)

    # ── Step 4: Catalog lookup (librarian + multi-tool) ───────────────────────
    catalog_section = ""

    if persona == "librarian":
        # Librarian: return catalog results directly — no Gemini needed
        tools_used.append("catalog_search")
        catalog_section = find_materials(
            question=question,
            grade=ctx_hints.get("grade"),
            subject=ctx_hints.get("subject"),
            term=ctx_hints.get("term"),
            year=ctx_hints.get("year"),
            audience=ctx_hints.get("audience"),
            history=history,
        )
        return {
            "persona": persona,
            "answer": catalog_section,
            "sources": _source_urls(hits),
            "tools": tools_used,
        }

    # Non-librarian personas: optionally append catalog results
    if _wants_resources(question) or ctx_hints.get("grade") or ctx_hints.get("subject"):
        tools_used.append("catalog_search")
        catalog_section = _catalog_context(question, ctx_hints)

    # ── Step 5: Build prompt ──────────────────────────────────────────────────
    prompt = _build_prompt(persona, question, qdrant_ctx, history)

    # ── Step 6: Gemini generation ─────────────────────────────────────────────
    tools_used.append("gemini_generate")
    raw_answer = generate(prompt)

    # ── Step 7: Optionally run quiz tool alongside teaching ───────────────────
    quiz_section = ""
    if persona == "teacher" and _wants_quiz(question):
        tools_used.append("quiz_generate")
        quiz_prompt_str = build_quiz_prompt(question, qdrant_ctx)
        quiz_section = generate(quiz_prompt_str)

    # ── Step 8: Clean and assemble output ────────────────────────────────────
    answer = clean_answer(raw_answer)
    answer = rewrite_links(answer)

    if quiz_section:
        answer += "\n\n---\nQuiz\n\n" + clean_answer(quiz_section)

    if catalog_section:
        answer += "\n\n---\nRecommended Materials\n\n" + catalog_section

    # ── Step 9: Sources ───────────────────────────────────────────────────────
    sources = _source_urls(hits)

    return {
        "persona": persona,
        "answer": answer,
        "sources": sources,
        "tools": tools_used,
    }
