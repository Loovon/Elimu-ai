"""
elimu_ai/db/repositories.py  —  All PostgreSQL repository classes.
Rules: no raw SQL outside this file, all methods degrade gracefully.
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
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.warning("db[%s]: %s", fn.__qualname__, exc)
            return None
    return wrapper


# ── Memory ────────────────────────────────────────────────────────────────────

class MemoryRepository:
    @_db_op
    def save_summary(self, session_id, user_id, summary):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_memory_summary(session_id,user_id,summary,created_at)"
                    " VALUES(%s,%s,%s,%s)"
                    " ON CONFLICT(session_id) DO UPDATE"
                    " SET summary=EXCLUDED.summary, created_at=EXCLUDED.created_at",
                    (session_id, user_id, summary, _now()),
                )

    @_db_op
    def get_summaries(self, user_id, limit=3):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT summary FROM ai_memory_summary"
                    " WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cur.fetchall()
        return [r[0] for r in (rows or [])]

    @_db_op
    def get_summary(self, session_id):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT summary FROM ai_memory_summary WHERE session_id=%s",
                    (session_id,),
                )
                row = cur.fetchone()
        return row[0] if row else None


# ── Analytics ─────────────────────────────────────────────────────────────────

class AnalyticsRepository:
    @_db_op
    def log_request(self, request_id, user_id, persona, intents, tools_used,
                    question_len, answer_len, execution_ms, had_error=False,
                    session_id=None):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_analytics_log"
                    "(request_id,user_id,session_id,persona,intents,tools_used,"
                    " question_len,answer_len,execution_ms,had_error,created_at)"
                    " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (request_id, user_id, session_id, persona,
                     json.dumps(intents), json.dumps(tools_used),
                     question_len, answer_len, execution_ms, had_error, _now()),
                )


# ── Scheduler ─────────────────────────────────────────────────────────────────

class SchedulerRepository:
    @_db_op
    def log_job(self, job_name, status, result, duration_ms, error=None):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_scheduler_log"
                    "(job_name,status,result,duration_ms,error,ran_at)"
                    " VALUES(%s,%s,%s,%s,%s,%s)",
                    (job_name, status, (result or "")[:500], duration_ms, error, _now()),
                )

    @_db_op
    def get_recent_jobs(self, limit=20):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT job_name,status,result,duration_ms,error,ran_at"
                    " FROM ai_scheduler_log ORDER BY ran_at DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
        if not rows:
            return []
        return [{"job_name":r[0],"status":r[1],"result":r[2],
                 "duration_ms":r[3],"error":r[4],"ran_at":r[5]} for r in rows]


# ── Quiz ──────────────────────────────────────────────────────────────────────

class QuizRepository:
    @_db_op
    def save_quiz(self, session_id, user_id, question, quiz_content,
                  subject=None, grade=None):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_quiz"
                    "(session_id,user_id,question,quiz_content,subject,grade,created_at,is_ai)"
                    " VALUES(%s,%s,%s,%s,%s,%s,%s,TRUE)",
                    (session_id, user_id, (question or "")[:500],
                     quiz_content, subject, grade, _now()),
                )

    @_db_op
    def get_recent_quizzes(self, user_id, limit=5):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT question,quiz_content,subject,grade,created_at"
                    " FROM ai_quiz WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cur.fetchall()
        if not rows:
            return []
        return [{"question":r[0],"quiz_content":r[1],"subject":r[2],
                 "grade":r[3],"created_at":r[4]} for r in rows]


# ── Recommendation ────────────────────────────────────────────────────────────

class RecommendationRepository:
    @_db_op
    def save_recommendation(self, user_id, session_id, question, results_json,
                             grade=None, subject=None):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_recommendation_log"
                    "(user_id,session_id,question,results_json,grade,subject,created_at)"
                    " VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (user_id, session_id, (question or "")[:500],
                     results_json, grade, subject, _now()),
                )

    @_db_op
    def get_cached(self, cache_key: str) -> Optional[str]:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT result_json FROM ai_recommendation_cache"
                    " WHERE cache_key=%s AND (expires_at IS NULL OR expires_at > NOW())",
                    (cache_key,),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE ai_recommendation_cache SET hit_count=hit_count+1"
                        " WHERE cache_key=%s", (cache_key,)
                    )
        return row[0] if row else None

    @_db_op
    def set_cached(self, cache_key: str, result_json: str, ttl_hours: int = 6) -> None:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_recommendation_cache(cache_key,result_json,expires_at,created_at)"
                    " VALUES(%s,%s,NOW()+INTERVAL '%s hours',%s)"
                    " ON CONFLICT(cache_key) DO UPDATE"
                    " SET result_json=EXCLUDED.result_json, expires_at=EXCLUDED.expires_at",
                    (cache_key, result_json, ttl_hours, _now()),
                )


# ── Agent Log (decisions + failures + hallucinations + alerts) ────────────────

class AgentLogRepository:
    @_db_op
    def log_decision(self, request_id, session_id, user_id, question,
                     intents, plan_steps, tools_used, persona,
                     confidence, execution_ms, had_error):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_agent_decisions"
                    "(request_id,session_id,user_id,question,intents,plan_steps,"
                    " tools_used,persona,confidence,execution_ms,had_error,created_at)"
                    " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (request_id, session_id, user_id, (question or "")[:500],
                     json.dumps(intents), json.dumps(plan_steps),
                     json.dumps(tools_used), persona, confidence,
                     execution_ms, had_error, _now()),
                )

    @_db_op
    def log_success(self, question, intents, tools, persona,
                    execution_ms, user_id=None, session_id=None):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_successful_queries"
                    "(question,intents,tools_used,persona,execution_ms,user_id,session_id,created_at)"
                    " VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    ((question or "")[:500], json.dumps(intents),
                     json.dumps(tools), persona, execution_ms,
                     user_id, session_id, _now()),
                )

    @_db_op
    def log_failure(self, question, intents, tools, failure_reason,
                    stack_trace="", confidence=0.0, user_id=None,
                    session_id=None, suggested_fix=""):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_failed_queries"
                    "(question,intents,tools_used,failure_reason,stack_trace,"
                    " confidence,user_id,session_id,suggested_fix,created_at)"
                    " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    ((question or "")[:500], json.dumps(intents),
                     json.dumps(tools), (failure_reason or "")[:500],
                     (stack_trace or "")[:2000], confidence,
                     user_id, session_id, suggested_fix, _now()),
                )

    @_db_op
    def log_hallucination(self, question, answer, issues, confidence, user_id=None):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_hallucinations"
                    "(question,answer,issues,confidence,user_id,created_at)"
                    " VALUES(%s,%s,%s,%s,%s,%s)",
                    ((question or "")[:500], (answer or "")[:500],
                     json.dumps(issues), confidence, user_id, _now()),
                )

    @_db_op
    def log_alert(self, alert_type, subject, body, traceback_text="", suggested_fix=""):
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_email_notifications"
                    "(alert_type,subject,body,traceback_text,suggested_fix,sent_at)"
                    " VALUES(%s,%s,%s,%s,%s,%s)",
                    (alert_type, (subject or "")[:200], (body or "")[:1000],
                     (traceback_text or "")[:2000], suggested_fix, _now()),
                )

    @_db_op
    def get_recent_failures(self, limit=10) -> List[Dict[str, Any]]:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT question,intents,tools_used,failure_reason,created_at"
                    " FROM ai_failed_queries ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
        if not rows:
            return []
        return [{"question":r[0],"intents":r[1],"tools":r[2],
                 "failure":r[3],"at":r[4]} for r in rows]

    @_db_op
    def get_unresolved_failures(
        self,
        max_retries: int = 3,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Return failed queries that have not yet been resolved and have not
        exceeded the retry limit.  Used by the scheduler retry job.
        """
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id,question,intents,tools_used,failure_reason,"
                    " confidence,suggested_fix,retry_count,created_at"
                    " FROM ai_failed_queries"
                    " WHERE resolved = FALSE AND retry_count < %s"
                    " ORDER BY created_at ASC LIMIT %s",
                    (max_retries, limit),
                )
                rows = cur.fetchall()
        if not rows:
            return []
        return [
            {
                "id":            r[0],
                "question":      r[1],
                "intents":       r[2],
                "tools":         r[3],
                "failure_reason":r[4],
                "confidence":    r[5],
                "suggested_fix": r[6],
                "retry_count":   r[7],
                "created_at":    r[8],
            }
            for r in rows
        ]

    def get_unresolved_failures_safe(
        self,
        max_retries: int = 3,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Wrapper that always returns a list — never None — even on DB failure."""
        result = self.get_unresolved_failures(max_retries=max_retries, limit=limit)
        return result if result is not None else []

    @_db_op
    def increment_retry(self, failure_id: int) -> None:
        """Increment retry_count for a single failed query row."""
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ai_failed_queries SET retry_count = retry_count + 1"
                    " WHERE id = %s",
                    (failure_id,),
                )

    @_db_op
    def mark_resolved(self, failure_id: int) -> None:
        """Mark a failed query as resolved after a successful retry."""
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ai_failed_queries SET resolved = TRUE"
                    " WHERE id = %s",
                    (failure_id,),
                )

    @_db_op
    def log_health_report(self, status: str, report: dict) -> None:
        from elimu_ai.db.connection import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_health_reports(status,report,reported_at)"
                    " VALUES(%s,%s,%s)",
                    (status, json.dumps(report), _now()),
                )
