"""
app.py — ASGI entry point.
uvicorn app:application --reload
gunicorn app:application -k uvicorn.workers.UvicornWorker
"""

import logging
import os

from elimu_ai.service import app as application  # noqa: F401

_log = logging.getLogger(__name__)

# ── APScheduler ───────────────────────────────────────────────────────────────
if os.getenv("DISABLE_SCHEDULER", "").lower() not in ("1", "true", "yes"):
    try:
        from elimu_ai.scheduler import start_scheduler
        start_scheduler(daemon=True)
    except Exception as exc:
        _log.warning("Scheduler failed to start: %s", exc)

# ── Agent Manager ─────────────────────────────────────────────────────────────
if os.getenv("DISABLE_AGENT_MANAGER", "").lower() not in ("1", "true", "yes"):
    try:
        from elimu_ai.agent_manager import start_agent_manager
        start_agent_manager(daemon=True)
    except Exception as exc:
        _log.warning("AgentManager failed to start: %s", exc)

# ── DB Migrations ─────────────────────────────────────────────────────────────
if os.getenv("DISABLE_DB_MIGRATIONS", "").lower() not in ("1", "true", "yes"):
    try:
        from elimu_ai.db.migrations import run_migrations
        run_migrations()
    except Exception as exc:
        _log.warning("DB migrations failed (non-fatal): %s", exc)
