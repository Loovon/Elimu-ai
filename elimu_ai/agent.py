"""
elimu_ai/agent.py

Agent entry point — backward-compatible orchestration facade.

The public API surface (run_agent) is UNCHANGED.
Internally it delegates to the Orchestrator, which supports:
  - multi-intent detection
  - tool registry execution plans
  - sequential tool chaining
  - context building
  - memory and analytics

Existing callers (service.py, main.py) require no changes.
The response dict shape is preserved exactly:
    {
        "persona":  str,
        "answer":   str,
        "sources":  list[str],
        "tools":    list[str],
    }
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def run_agent(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute the autonomous agent pipeline for a single user request.

    Parameters
    ----------
    question : str
        The user's message.
    history : list of {role: str, content: str}, optional
        Prior conversation turns for context.
    session_id : str, optional
        Session identifier for memory / analytics.
    user_id : int, optional
        Authenticated user ID for personalisation and analytics.
    request_id : str, optional
        Unique trace ID (auto-generated if not provided).

    Returns
    -------
    dict — UNCHANGED from previous versions:
        persona  : str         — primary persona / intent name
        answer   : str         — clean plain-text response
        sources  : list[str]   — referral-tagged Qdrant source URLs
        tools    : list[str]   — tools invoked during this request
    """
    from elimu_ai.orchestrator import run_orchestrator

    # Coerce None to empty string so the orchestrator's guard handles it
    if question is None:
        question = ""

    result = run_orchestrator(
        question=question,
        history=history or [],
        session_id=session_id,
        user_id=user_id,
        request_id=request_id,
    )

    # Return the exact same dict shape that service.py and main.py expect
    return {
        "persona": result.persona,
        "answer":  result.answer,
        "sources": result.sources,
        "tools":   result.tools,
    }
