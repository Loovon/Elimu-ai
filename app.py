"""
app.py

ASGI entry point — the only file Uvicorn / Gunicorn should point at.

Exposes:
  application  — the FastAPI app from elimu_ai.service

Also starts background workers on process startup:
  - APScheduler (background tasks)
  - AgentManager (continuous observer)

Run locally:
    uvicorn app:application --reload

Production:
    gunicorn app:application -k uvicorn.workers.UvicornWorker --workers 2

Disable background workers:
    DISABLE_SCHEDULER=1 uvicorn app:application
"""

import logging
import os

from elimu_ai.service import app as application  # noqa: F401

_log = logging.getLogger(__name__)

# ── Start APScheduler ─────────────────────────────────────────────────────────
if os.getenv("DISABLE_SCHEDULER", "").lower() not in ("1", "true", "yes"):
    try:
        from elimu_ai.scheduler import start_scheduler
        start_scheduler(daemon=True)
    except Exception as exc:
        _log.warning("Scheduler could not start: %s", exc)

# ── Start AgentManager ────────────────────────────────────────────────────────
if os.getenv("DISABLE_AGENT_MANAGER", "").lower() not in ("1", "true", "yes"):
    try:
        from elimu_ai.agent_manager import start_agent_manager
        start_agent_manager(daemon=True)
    except Exception as exc:
        _log.warning("AgentManager could not start: %s", exc)

# ── Run DB migrations (idempotent, non-fatal) ─────────────────────────────────
if os.getenv("DISABLE_DB_MIGRATIONS", "").lower() not in ("1", "true", "yes"):
    try:
        from elimu_ai.db.migrations import run_migrations
        run_migrations()
    except Exception as exc:
        _log.warning("DB migrations failed (non-fatal): %s", exc)
