"""
elimu_ai/agents/learning.py

Learning Agent — records failures and successes to improve routing over time.

Stores every:
  - Failed search
  - Misunderstood query
  - Hallucination
  - Tool failure
  - Timeout
  - Recommendation failure

Provides analysis for routing improvement.
All storage is non-fatal — never crashes the main pipeline.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LearningAgent:
    """
    Records outcomes and logs them to PostgreSQL for future routing improvement.
    """

    def record_success(
        self,
        question: str,
        intents: List[str],
        tools_used: List[str],
        persona: str,
        execution_ms: int,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Record a successful query execution."""
        try:
            from elimu_ai.db.repositories import AgentLogRepository
            repo = AgentLogRepository()
            repo.log_success(
                question=question,
                intents=intents,
                tools=tools_used,
                persona=persona,
                execution_ms=execution_ms,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception as exc:
            logger.debug("LearningAgent.record_success: %s", exc)

    def record_failure(
        self,
        question: str,
        intents: List[str],
        tools_used: List[str],
        failure_reason: str,
        exc: Optional[Exception] = None,
        confidence: float = 0.0,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        suggested_fix: str = "",
    ) -> None:
        """Record a failed query execution with full context."""
        tb = ""
        if exc:
            tb = traceback.format_exc()

        logger.warning(
            "LearningAgent: failure recorded — reason=%r intents=%s tools=%s",
            failure_reason[:80], intents, tools_used,
        )

        try:
            from elimu_ai.db.repositories import AgentLogRepository
            repo = AgentLogRepository()
            repo.log_failure(
                question=question,
                intents=intents,
                tools=tools_used,
                failure_reason=failure_reason,
                stack_trace=tb,
                confidence=confidence,
                user_id=user_id,
                session_id=session_id,
                suggested_fix=suggested_fix,
            )
        except Exception as db_exc:
            logger.debug("LearningAgent.record_failure DB: %s", db_exc)

    def record_hallucination(
        self,
        question: str,
        answer: str,
        issues: List[str],
        confidence: float,
        user_id: Optional[int] = None,
    ) -> None:
        """Record a detected hallucination."""
        logger.warning(
            "LearningAgent: hallucination detected — confidence=%.2f issues=%s",
            confidence, issues,
        )
        try:
            from elimu_ai.db.repositories import AgentLogRepository
            repo = AgentLogRepository()
            repo.log_hallucination(
                question=question,
                answer=answer[:500],
                issues=issues,
                confidence=confidence,
                user_id=user_id,
            )
        except Exception as exc:
            logger.debug("LearningAgent.record_hallucination: %s", exc)

    def get_routing_insights(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Return recent failure patterns for routing improvement.
        Returns [] if DB unavailable.
        """
        try:
            from elimu_ai.db.repositories import AgentLogRepository
            repo = AgentLogRepository()
            return repo.get_recent_failures(limit=limit) or []
        except Exception:
            return []
