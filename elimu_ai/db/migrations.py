"""
elimu_ai/db/migrations.py

Database schema initialisation for the Elimu AI tables.

Run once at deployment:
    from elimu_ai.db.migrations import run_migrations
    run_migrations()

Or via management command:
    python -c "from elimu_ai.db.migrations import run_migrations; run_migrations()"

All tables are prefixed with `ai_` to avoid collisions with Django models.
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
CREATE INDEX IF NOT EXISTS idx_analytics_user   ON ai_analytics_log(user_id);
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
"""


def run_migrations() -> bool:
    """
    Create all AI tables if they don't exist.
    Returns True on success, False on failure.
    """
    try:
        from elimu_ai.db.connection import get_connection, db_available
        if not db_available():
            logger.warning("migrations: DB not available — skipping.")
            return False
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)
        logger.info("migrations: AI schema applied successfully.")
        return True
    except Exception as exc:
        logger.error("migrations: failed: %s", exc)
        return False
