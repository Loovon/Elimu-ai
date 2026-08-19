"""
elimu_ai/db/migrations.py

Complete database schema for the Elimu AI autonomous platform.
All tables prefixed with ai_ to avoid collisions with Django models.

Run:
    from elimu_ai.db.migrations import run_migrations
    run_migrations()
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SCHEMA = """
-- Conversation memory summaries
CREATE TABLE IF NOT EXISTS ai_memory_summary (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR(128) UNIQUE NOT NULL,
    user_id     INTEGER,
    summary     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_memory_user ON ai_memory_summary(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_session ON ai_memory_summary(session_id);

-- Request/response analytics
CREATE TABLE IF NOT EXISTS ai_analytics_log (
    id           SERIAL PRIMARY KEY,
    request_id   VARCHAR(64) NOT NULL,
    user_id      INTEGER,
    session_id   VARCHAR(128),
    persona      VARCHAR(32),
    intents      JSONB,
    tools_used   JSONB,
    question_len INTEGER,
    answer_len   INTEGER,
    execution_ms INTEGER,
    had_error    BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analytics_user    ON ai_analytics_log(user_id);
CREATE INDEX IF NOT EXISTS idx_analytics_persona ON ai_analytics_log(persona);
CREATE INDEX IF NOT EXISTS idx_analytics_created ON ai_analytics_log(created_at);

-- Background job run history
CREATE TABLE IF NOT EXISTS ai_scheduler_log (
    id           SERIAL PRIMARY KEY,
    job_name     VARCHAR(64) NOT NULL,
    status       VARCHAR(16) NOT NULL,
    result       TEXT,
    duration_ms  INTEGER,
    error        TEXT,
    ran_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scheduler_job    ON ai_scheduler_log(job_name);
CREATE INDEX IF NOT EXISTS idx_scheduler_ran_at ON ai_scheduler_log(ran_at);

-- AI-generated quizzes
CREATE TABLE IF NOT EXISTS ai_quiz (
    id           SERIAL PRIMARY KEY,
    session_id   VARCHAR(128),
    user_id      INTEGER,
    question     TEXT,
    quiz_content TEXT NOT NULL,
    subject      VARCHAR(64),
    grade        VARCHAR(32),
    is_ai        BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_quiz_user    ON ai_quiz(user_id);
CREATE INDEX IF NOT EXISTS idx_quiz_subject ON ai_quiz(subject);

-- Recommendation log/cache
CREATE TABLE IF NOT EXISTS ai_recommendation_log (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER,
    session_id   VARCHAR(128),
    question     TEXT,
    results_json TEXT,
    grade        VARCHAR(32),
    subject      VARCHAR(64),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rec_user    ON ai_recommendation_log(user_id);
CREATE INDEX IF NOT EXISTS idx_rec_subject ON ai_recommendation_log(subject);

-- Agent decision logs (every supervisor decision)
CREATE TABLE IF NOT EXISTS ai_agent_decisions (
    id           SERIAL PRIMARY KEY,
    request_id   VARCHAR(64),
    session_id   VARCHAR(128),
    user_id      INTEGER,
    question     TEXT,
    intents      JSONB,
    plan_steps   JSONB,
    tools_used   JSONB,
    persona      VARCHAR(32),
    confidence   FLOAT,
    execution_ms INTEGER,
    had_error    BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_decisions_request ON ai_agent_decisions(request_id);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON ai_agent_decisions(created_at);

-- Successful query log
CREATE TABLE IF NOT EXISTS ai_successful_queries (
    id           SERIAL PRIMARY KEY,
    question     TEXT NOT NULL,
    intents      JSONB,
    tools_used   JSONB,
    persona      VARCHAR(32),
    execution_ms INTEGER,
    user_id      INTEGER,
    session_id   VARCHAR(128),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_success_created ON ai_successful_queries(created_at);

-- Failed query log
CREATE TABLE IF NOT EXISTS ai_failed_queries (
    id             SERIAL PRIMARY KEY,
    question       TEXT NOT NULL,
    intents        JSONB,
    tools_used     JSONB,
    failure_reason TEXT,
    stack_trace    TEXT,
    confidence     FLOAT,
    user_id        INTEGER,
    session_id     VARCHAR(128),
    suggested_fix  TEXT,
    retry_count    INTEGER DEFAULT 0,
    resolved       BOOLEAN DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_failed_created  ON ai_failed_queries(created_at);
CREATE INDEX IF NOT EXISTS idx_failed_resolved ON ai_failed_queries(resolved, retry_count);

-- Intent history (for routing improvement)
CREATE TABLE IF NOT EXISTS ai_intent_history (
    id          SERIAL PRIMARY KEY,
    question    TEXT NOT NULL,
    detected    JSONB,
    primary_int VARCHAR(32),
    used_gemini BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_intent_primary ON ai_intent_history(primary_int);

-- Hallucination log
CREATE TABLE IF NOT EXISTS ai_hallucinations (
    id         SERIAL PRIMARY KEY,
    question   TEXT,
    answer     TEXT,
    issues     JSONB,
    confidence FLOAT,
    user_id    INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Response quality log
CREATE TABLE IF NOT EXISTS ai_response_quality (
    id           SERIAL PRIMARY KEY,
    request_id   VARCHAR(64),
    confidence   FLOAT,
    issues       JSONB,
    passed       BOOLEAN,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- User preferences / interests
CREATE TABLE IF NOT EXISTS ai_user_preferences (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER UNIQUE NOT NULL,
    preferred_grades JSONB,
    preferred_subj   JSONB,
    frequent_searches JSONB,
    last_seen        TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_prefs_user ON ai_user_preferences(user_id);

-- Background task log
CREATE TABLE IF NOT EXISTS ai_background_tasks (
    id           SERIAL PRIMARY KEY,
    task_name    VARCHAR(64) NOT NULL,
    status       VARCHAR(16) NOT NULL,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    duration_ms  INTEGER,
    result       TEXT,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Email alert log
CREATE TABLE IF NOT EXISTS ai_email_notifications (
    id             SERIAL PRIMARY KEY,
    alert_type     VARCHAR(64),
    subject        TEXT,
    body           TEXT,
    traceback_text TEXT,
    suggested_fix  TEXT,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Health reports
CREATE TABLE IF NOT EXISTS ai_health_reports (
    id           SERIAL PRIMARY KEY,
    status       VARCHAR(16),
    report       JSONB,
    reported_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Recommendation cache (for frequently requested materials)
CREATE TABLE IF NOT EXISTS ai_recommendation_cache (
    id          SERIAL PRIMARY KEY,
    cache_key   VARCHAR(256) UNIQUE NOT NULL,
    result_json TEXT NOT NULL,
    hit_count   INTEGER DEFAULT 0,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cache_key ON ai_recommendation_cache(cache_key);
CREATE INDEX IF NOT EXISTS idx_cache_exp ON ai_recommendation_cache(expires_at);
"""


def run_migrations() -> bool:
    """
    Create all AI tables if they don't exist.
    Returns True on success, False on failure.
    Idempotent — safe to run multiple times.
    """
    try:
        from elimu_ai.db.connection import get_connection, db_available
        if not db_available():
            logger.warning("migrations: DB not available — skipping.")
            return False
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)
                # Backward-compatible additions for existing deployments
                _apply_incremental(cur)
        logger.info("migrations: AI schema applied successfully.")
        return True
    except Exception as exc:
        logger.error("migrations: failed: %s", exc)
        return False


def _apply_incremental(cur) -> None:
    """
    ADD COLUMN statements that are safe to run on an already-created table.
    Uses DO $$ ... $$ blocks so they are no-ops if the column already exists.
    """
    incremental_stmts = [
        # retry_count and resolved for the learning loop
        """
        DO $$ BEGIN
            ALTER TABLE ai_failed_queries ADD COLUMN retry_count INTEGER DEFAULT 0;
        EXCEPTION WHEN duplicate_column THEN NULL; END $$;
        """,
        """
        DO $$ BEGIN
            ALTER TABLE ai_failed_queries ADD COLUMN resolved BOOLEAN DEFAULT FALSE;
        EXCEPTION WHEN duplicate_column THEN NULL; END $$;
        """,
        # Index for the retry scheduler query
        """
        CREATE INDEX IF NOT EXISTS idx_failed_resolved
            ON ai_failed_queries(resolved, retry_count);
        """,
    ]
    for stmt in incremental_stmts:
        try:
            cur.execute(stmt)
        except Exception as exc:
            logger.warning("migrations: incremental stmt skipped: %s", exc)
