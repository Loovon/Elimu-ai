"""
elimu_ai/orchestrator.py

AI Orchestrator — the execution engine of the agentic platform.

Responsibilities:
  1. Detect multiple intents using confidence scoring
  2. Extract curriculum context hints
  3. Search Qdrant for semantic context
  4. Build the full prompt context
  5. Look up tools from the registry
  6. Execute tools sequentially (with retries)
  7. Merge tool results into a single answer
  8. Save analytics and memory
  9. Return a structured OrchestratorResult

The orchestrator replaces the single-persona branch logic in agent.py.
The existing run_agent() function delegates to run_orchestrator() and
maps the result back to the legacy response shape for API compatibility.

Rules:
  - No UI code. No HTTP code.
  - Orchestrator owns execution; tools own logic.
  - All errors are caught and included in the result, never raised.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from elimu_ai.intent import detect_intents, IntentResult
from elimu_ai.context_builder import build_context, PromptContext
from elimu_ai.tool_registry import registry
from elimu_ai.qdrant_db import search as qdrant_search
from elimu_ai.helpers import clean_answer, rewrite_links, referral_url
from elimu_ai.tools.teacher import extract_context_hints, extract_context_from_history

logger = logging.getLogger(__name__)

# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class OrchestratorResult:
    """
    Structured result from one orchestrator run.

    Fields match the existing API response schema so service.py needs
    no changes to remain backward compatible.
    """
    request_id: str
    persona: str                           # primary intent name (for API compat)
    answer: str                            # merged plain-text answer
    sources: List[str]                     # referral-tagged source URLs
    tools: List[str]                       # tool names that were invoked
    intents: List[IntentResult]            # all detected intents
    execution_ms: int = 0
    had_error: bool = False
    error_detail: str = ""
    tool_outputs: Dict[str, str] = field(default_factory=dict)


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_orchestrator(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
    request_id: Optional[str] = None,
) -> OrchestratorResult:
    """
    Execute the full agentic pipeline.

    Parameters
    ----------
    question : str
        The user's message.
    history : list, optional
        Prior conversation turns [{role, content}].
    session_id : str, optional
        Session identifier for memory / analytics.
    user_id : int, optional
        Authenticated user ID.
    request_id : str, optional
        Unique request trace ID (auto-generated if not provided).

    Returns
    -------
    OrchestratorResult
    """
    t_start = time.monotonic()
    request_id = request_id or str(uuid.uuid4())
    history    = history or []

    logger.info(
        "orchestrator: request_id=%s question=%r session=%s user=%s",
        request_id[:8], question[:80], session_id, user_id,
    )

    if not question or not str(question).strip():
        return OrchestratorResult(
            request_id=request_id,
            persona="teacher",
            answer="Please ask a question and I'll be happy to help!",
            sources=[],
            tools=[],
            intents=[],
        )

    # ── 1. Detect intents ─────────────────────────────────────────────────────
    intents = detect_intents(question)
    intent_names = [i.name for i in intents]
    primary = intent_names[0] if intent_names else "teacher"

    logger.info(
        "orchestrator: intents=%s",
        [(i.name, round(i.confidence, 2)) for i in intents],
    )

    # ── 2. Extract curriculum context ─────────────────────────────────────────
    ctx_hints = extract_context_hints(question)
    if history:
        hist_hints = extract_context_from_history(history[-6:])
        for key in ("grade", "subject", "term", "year", "audience"):
            if not ctx_hints.get(key) and hist_hints.get(key):
                ctx_hints[key] = hist_hints[key]

    # ── 3. Qdrant search ──────────────────────────────────────────────────────
    qdrant_hits = []
    try:
        qdrant_hits = qdrant_search(question)
    except Exception as exc:
        logger.warning("orchestrator: Qdrant search failed: %s", exc)

    # ── 4. Catalog context (pre-fetch for non-librarian tools) ───────────────
    catalog_str = ""
    if any(i.name in ("librarian", "recommendation", "catalog") for i in intents):
        catalog_str = _fetch_catalog(question, ctx_hints)

    # ── 5. Build prompt context ───────────────────────────────────────────────
    ctx = build_context(
        question=question,
        persona=primary,
        intents=intent_names,
        history=history,
        curriculum_hints=ctx_hints,
        qdrant_hits=qdrant_hits,
        catalog_results=catalog_str,
    )

    # ── 6. Build execution plan ───────────────────────────────────────────────
    tools_plan = registry.execution_plan(intent_names)
    logger.info(
        "orchestrator: execution plan = %s",
        [t.name for t in tools_plan],
    )

    # ── 7. Execute tools ──────────────────────────────────────────────────────
    tool_outputs: Dict[str, str] = {}
    tools_used: List[str] = ["qdrant_search"]
    had_error = False
    error_detail = ""

    for tool_def in tools_plan:
        try:
            logger.debug("orchestrator: executing tool %r", tool_def.name)
            output = tool_def.execute(context=ctx, question=question)
            tool_outputs[tool_def.name] = output or ""
            tools_used.append(tool_def.name)
        except Exception as exc:
            logger.error(
                "orchestrator: tool %r failed: %s", tool_def.name, exc, exc_info=True
            )
            had_error = True
            error_detail = str(exc)
            tool_outputs[tool_def.name] = f"[{tool_def.name} failed: {exc}]"

    # ── 8. Merge tool outputs ─────────────────────────────────────────────────
    answer = _merge_outputs(tool_outputs, intents, question)
    answer = clean_answer(answer)
    answer = rewrite_links(answer)

    # ── 9. Source URLs ────────────────────────────────────────────────────────
    sources = _extract_sources(qdrant_hits)

    execution_ms = int((time.monotonic() - t_start) * 1000)

    logger.info(
        "orchestrator: done request_id=%s persona=%s tools=%s ms=%d",
        request_id[:8], primary, tools_used, execution_ms,
    )

    # ── 10. Analytics (non-blocking) ──────────────────────────────────────────
    _save_analytics(
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        persona=primary,
        intents=intent_names,
        tools_used=tools_used,
        question=question,
        answer=answer,
        execution_ms=execution_ms,
        had_error=had_error,
    )

    # ── 11. Memory update ─────────────────────────────────────────────────────
    if session_id:
        _update_memory(session_id, question, answer, user_id)

    return OrchestratorResult(
        request_id=request_id,
        persona=primary,
        answer=answer,
        sources=sources,
        tools=tools_used,
        intents=intents,
        execution_ms=execution_ms,
        had_error=had_error,
        error_detail=error_detail,
        tool_outputs=tool_outputs,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_catalog(question: str, ctx_hints: Dict) -> str:
    """Run a catalog search and return formatted results."""
    try:
        from elimu_ai.catalog_search import (
            catalog_available, search_catalog, format_recommendations,
        )
        if not catalog_available():
            return ""
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
        logger.warning("orchestrator: catalog fetch failed: %s", exc)
        return ""


def _merge_outputs(
    tool_outputs: Dict[str, str],
    intents: List[IntentResult],
    question: str,
) -> str:
    """
    Intelligently merge multiple tool outputs into one response.

    Strategy:
    - If only one tool ran, return its output directly.
    - If multiple tools ran, join with clear section separators.
    - Moderation always appears last if present.
    """
    if not tool_outputs:
        return "I was unable to generate a response. Please try again."

    # Strip tool failure markers for display
    clean_outputs = {
        name: text
        for name, text in tool_outputs.items()
        if text and not text.startswith("[") and not text.endswith("]")
    }

    if not clean_outputs:
        return "I encountered an error processing your request. Please try again."

    if len(clean_outputs) == 1:
        return list(clean_outputs.values())[0]

    # Multi-tool: label each section
    _LABELS = {
        "teacher":       "Explanation",
        "quiz":          "Practice Quiz",
        "librarian":     "Materials",
        "recommendation":"Recommended Materials",
        "community":     "Discussion",
        "catalog":       "Catalog Results",
        "moderation":    "Content Check",
    }

    # Order: teacher → recommendation/librarian → quiz → community → catalog
    _ORDER = ["teacher", "recommendation", "librarian", "quiz", "community", "catalog", "moderation"]
    ordered_names = sorted(
        clean_outputs.keys(),
        key=lambda n: _ORDER.index(n) if n in _ORDER else 99,
    )

    parts = []
    for name in ordered_names:
        label = _LABELS.get(name, name.title())
        parts.append(f"{label}\n\n{clean_outputs[name]}")

    return "\n\n---\n\n".join(parts)


def _extract_sources(hits: List) -> List[str]:
    """Extract referral-tagged source URLs from Qdrant hits."""
    sources = []
    for hit in hits:
        try:
            url = (hit.payload or {}).get("url", "")
            if url:
                sources.append(referral_url(url))
        except Exception:
            pass
    return sources


def _save_analytics(
    request_id: str,
    user_id: Optional[int],
    session_id: Optional[str],
    persona: str,
    intents: List[str],
    tools_used: List[str],
    question: str,
    answer: str,
    execution_ms: int,
    had_error: bool,
) -> None:
    """Save request analytics to DB (non-fatal)."""
    try:
        from elimu_ai.db.repositories import AnalyticsRepository
        repo = AnalyticsRepository()
        repo.log_request(
            request_id=request_id,
            user_id=user_id,
            persona=persona,
            intents=intents,
            tools_used=tools_used,
            question_len=len(question),
            answer_len=len(answer),
            execution_ms=execution_ms,
            had_error=had_error,
            session_id=session_id,
        )
    except Exception as exc:
        logger.debug("orchestrator: analytics save failed (non-fatal): %s", exc)


def _update_memory(
    session_id: str,
    question: str,
    answer: str,
    user_id: Optional[int],
) -> None:
    """Add turns to memory and trigger summary if due (non-fatal)."""
    try:
        from elimu_ai.memory import memory_store
        memory_store.add_turn(session_id, "user", question)
        memory_store.add_turn(session_id, "assistant", answer)
        if memory_store.should_summarise(session_id):
            memory_store.save_summary(session_id, user_id=user_id)
    except Exception as exc:
        logger.debug("orchestrator: memory update failed (non-fatal): %s", exc)
