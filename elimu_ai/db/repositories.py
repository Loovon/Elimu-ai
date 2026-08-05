"""
elimu_ai/db/repositories.py

PostgreSQL Repository classes.

Rules:
  - All DB writes pass through these classes.
  - Never execute raw SQL outside this module.
  - All methods degrade gracefully when DB is unavailable.
  - Never delete user content.
  - Never overwrite human posts.
  - AI-generated content is always flagged with is_ai=True.

Repositories:
  MemoryRepository         — conversation summaries
  AnalyticsRepository      — request/response analytics logs
  SchedulerRepository      — background job run history
  QuizRepository           — saved AI-generated quizzes
  RecommendationRepository — recommendation cache
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _db_op(fn):
    """Decorator: catch all exceptions and log them instead of raising."""
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.warning("db[%s]: %s", fn.__qualname__, exc)
            return None
    return wrapper


# ── Memory Repository ─────────────────────────────────────────────────────────

class MemoryRepository:
    """Stores and retrieves AI conversation summaries."""

    @_db_op
    def save_summary(
        self,
        session_id: str,
        user_id: Optional[int],
        summary: str,
    ) -> None:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_memory_summary
                        (session_id, user_id, summary, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE
                        SET summary = EXCLUDED.summary,
                            created_at = EXCLUDED.created_at
                    """,
                    (session_id, user_id, summary, _now()),
                )

    @_db_op
    def get_summaries(
        self,
        user_id: int,
        limit: int = 3,
    ) -> List[str]:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT summary FROM ai_memory_summary
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                rows = cur.fetchall()
        return [r[0] for r in (rows or [])]

    @_db_op
    def get_summary(self, session_id: str) -> Optional[str]:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT summary FROM ai_memory_summary WHERE session_id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
        return row[0] if row else None


# ── Analytics Repository ──────────────────────────────────────────────────────

class AnalyticsRepository:
    """Logs AI request/response analytics."""

    @_db_op
    def log_request(
        self,
        request_id: str,
        user_id: Optional[int],
        persona: str,
        intents: List[str],
        tools_used: List[str],
        question_len: int,
        answer_len: int,
        execution_ms: int,
        had_error: bool = False,
        session_id: Optional[str] = None,
    ) -> None:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_analytics_log
                        (request_id, user_id, session_id, persona, intents,
                         tools_used, question_len, answer_len,
                         execution_ms, had_error, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request_id, user_id, session_id, persona,
                        json.dumps(intents), json.dumps(tools_used),
                        question_len, answer_len,
                        execution_ms, had_error, _now(),
                    ),
                )


# ── Scheduler Repository ──────────────────────────────────────────────────────

class SchedulerRepository:
    """Persists background job run history."""

    @_db_op
    def log_job(
        self,
        job_name: str,
        status: str,
        result: str,
        duration_ms: int,
        error: Optional[str] = None,
    ) -> None:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_scheduler_log
                        (job_name, status, result, duration_ms, error, ran_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (job_name, status, result[:500], duration_ms, error, _now()),
                )

    @_db_op
    def get_recent_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT job_name, status, result, duration_ms, error, ran_at
                    FROM ai_scheduler_log
                    ORDER BY ran_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        if not rows:
            return []
        return [
            {
                "job_name":    r[0],
                "status":      r[1],
                "result":      r[2],
                "duration_ms": r[3],
                "error":       r[4],
                "ran_at":      r[5],
            }
            for r in rows
        ]


# ── Quiz Repository ───────────────────────────────────────────────────────────

class QuizRepository:
    """Stores AI-generated quizzes."""

    @_db_op
    def save_quiz(
        self,
        session_id: str,
        user_id: Optional[int],
        question: str,
        quiz_content: str,
        subject: Optional[str] = None,
        grade: Optional[str] = None,
    ) -> None:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_quiz
                        (session_id, user_id, question, quiz_content,
                         subject, grade, created_at, is_ai)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                    """,
                    (
                        session_id, user_id, question[:500],
                        quiz_content, subject, grade, _now(),
                    ),
                )

    @_db_op
    def get_recent_quizzes(
        self,
        user_id: int,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT question, quiz_content, subject, grade, created_at
                    FROM ai_quiz
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                rows = cur.fetchall()
        if not rows:
            return []
        return [
            {
                "question":     r[0],
                "quiz_content": r[1],
                "subject":      r[2],
                "grade":        r[3],
                "created_at":   r[4],
            }
            for r in rows
        ]


# ── Recommendation Repository ─────────────────────────────────────────────────

class RecommendationRepository:
    """Caches and logs AI recommendations."""

    @_db_op
    def save_recommendation(
        self,
        user_id: Optional[int],
        session_id: str,
        question: str,
        results_json: str,
        grade: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> None:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_recommendation_log
                        (user_id, session_id, question, results_json,
                         grade, subject, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id, session_id, question[:500],
                        results_json, grade, subject, _now(),
                    ),
                )
