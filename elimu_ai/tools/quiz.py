"""
elimu_ai/tools/quiz.py

Quiz tool — builds quiz prompts and handles Gemini fallback gracefully.
Responsibilities:
  - build_quiz_prompt(question, context) → str
  - quiz_fallback(question)              → str (catalog materials when Gemini fails)

Rules:
  - build_quiz_prompt() never calls Gemini — it only builds a prompt string.
  - quiz_fallback() uses catalog search only, not Gemini.
  - Never imports service.py.
  - No legacy ChromaDB / Ollama imports.
"""

from __future__ import annotations

from elimu_ai.prompts import QUIZ_PROMPT, QUIZ_FALLBACK


def build_quiz_prompt(question: str, context: str = "") -> str:
    """
    Render and return the quiz persona prompt string.
    Does NOT call Gemini.
    """
    return QUIZ_PROMPT.format(
        question=question,
        context=context or "No specific content found — use general Kenyan curriculum knowledge.",
    )


def quiz_fallback(question: str) -> str:
    """
    Return a graceful fallback message with catalog revision materials
    when Gemini is unavailable to generate a quiz.
    """
    from elimu_ai.catalog_search import search_catalog, format_recommendations
    from elimu_ai.tools.teacher import extract_context_hints

    ctx = extract_context_hints(question)
    try:
        results = search_catalog(
            grade=ctx.get("grade"),
            subject=ctx.get("subject"),
            term=ctx.get("term"),
            keyword=question,
            audience="student",
            max_results=4,
        )
        catalog_str = format_recommendations(results, question) if results else ""
    except Exception:
        catalog_str = ""

    if not catalog_str:
        from elimu_ai.helpers import search_url
        catalog_str = f"Search for revision materials here: {search_url(question)}"

    return QUIZ_FALLBACK.format(catalog_results=catalog_str)
