"""
elimu_ai/agent.py

Backward-compatible entry point.
Delegates to the SupervisorAgent when available,
falls back to the original orchestrator on any import failure.
Response shape is UNCHANGED: {persona, answer, sources, tools}
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
    Execute the autonomous agent pipeline.

    Returns the exact same dict shape as all previous versions:
        persona  : str
        answer   : str
        sources  : list[str]
        tools    : list[str]
    """
    if question is None:
        question = ""

    # ── Try SupervisorAgent first ─────────────────────────────────────────
    try:
        from elimu_ai.agents.supervisor import SupervisorAgent
        supervisor = SupervisorAgent()
        result = supervisor.run(
            question=question,
            history=history or [],
            session_id=session_id,
            user_id=user_id,
            request_id=request_id,
        )
        return {
            "persona": result.persona,
            "answer":  result.answer,
            "sources": result.sources,
            "tools":   result.tools_used,
        }
    except Exception as exc:
        logger.warning(
            "SupervisorAgent failed (%s) — falling back to orchestrator", exc
        )

    # ── Fallback to orchestrator ──────────────────────────────────────────
    from elimu_ai.orchestrator import run_orchestrator
    result = run_orchestrator(
        question=question,
        history=history or [],
        session_id=session_id,
        user_id=user_id,
        request_id=request_id,
    )
    return {
        "persona": result.persona,
        "answer":  result.answer,
        "sources": result.sources,
        "tools":   result.tools,
    }
